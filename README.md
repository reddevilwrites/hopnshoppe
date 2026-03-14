# hopnshoppe

A full-stack e-commerce demo built on a **microservices architecture** with aggregating catalog data from multiple sources such Content-as-a-Service (AEM CMS), PIM (REST),  legacy applications(SOAP based) and semantic product search powered by pgvector.

## Services

| Service | Port | Description |
|---|---|---|
| discovery-server | 8761 | Eureka service registry |
| config-server | 8888 | Spring Cloud Config server |
| api-gateway | 8080 | JWT validation + routing |
| auth-service | 8081 | Login / signup / JWT issuance |
| user-service | 8084 | User profile management |
| cart-service | 8082 | Cart state (database-per-service) |
| catalog-service | 8083 | Product aggregator — AEM GraphQL + DummyJSON Marketplace |
| search-service | 8085 | Hybrid search + 4-layer intelligent cache (FastAPI + pgvector) — v5.0.0 |
| ingestion-worker | — | Kafka consumer; generates embeddings and writes to search-db |
| frontend | 5173→80 | React 19 SPA served by nginx |
| auth-db | 5433 | PostgreSQL — credentials |
| user-db | 5434 | PostgreSQL — user profiles |
| cart-db | 5435 | PostgreSQL — cart items |
| search-db | 5436 | PostgreSQL + pgvector — search index |

> **Legacy monolith (`config-client`) has been deactivated.** Source files are preserved in the repository under `config-client/` but the service is excluded from the Maven build and Docker Compose. See `config-client/DEPRECATED.md`.

## Prerequisites
- Docker + Docker Compose
- Maven 3.9+ (for building JARs)
- Ports available: 5433–5436, 8080–8085, 8761, 8888, 5173
- A `.env` file with secrets (use `.env.example` as a template — keep `.env` out of git)

## Environment variables
Create `.env` in the repo root:
```
POSTGRES_USER=postgres
POSTGRES_PASSWORD=replace_me_with_strong_password

JWT_SECRET=replace_me_with_long_random_secret

# AEM / GraphQL (optional — catalog-service reads from config-server)
# GRAPHQL_ENDPOINT=http://host.docker.internal:8090/content/cq:graphql/wknd/endpoint.json
# GRAPHQL_API_KEY=replace_me_with_api_key
```

`docker-compose.yml` will fail fast (`?` syntax) if required variables are missing.

Search-service DB credentials are passed directly via `docker-compose.yml` environment blocks (not `.env`) and reuse `POSTGRES_PASSWORD`.

## Quick start
```bash
# 1. Build all JARs
mvn clean install -DskipTests

# 2. Start all services
docker compose up -d --build

# 3. Verify health
curl http://localhost:8080/actuator/health
```

Service endpoints:
- Eureka dashboard: http://localhost:8761
- Config server: http://localhost:8888/auth-service.yml
- Frontend: http://localhost:5173
- Search API: http://localhost:8085/search?q=running+shoes

Logs:
```bash
docker compose logs -f <service-name>
```

## Architecture

### Request flow
```
Browser → nginx (:5173) ─→ /api/*        → api-gateway (:8080) → lb://service → service
                          → /api/search/* → search-service (:8085) [no JWT required]
                          → /content/*   → AEM dispatcher (host.docker.internal:8090)
```

### Inter-service calls
| Caller | Callee | Endpoint | When |
|---|---|---|---|
| auth-service | user-service | `POST /internal/users` | Signup — with compensating rollback on failure |
| cart-service | catalog-service | `GET /products/unified/batch?ids=...` | Enrich cart DTOs with product data (AEM + Marketplace) |

### Product catalog
`catalog-service` aggregates products from two sources in parallel:

| Source | Type | ID Format |
|---|---|---|
| **AEM** (`source=AEM`) | Adobe Experience Manager content fragments via GraphQL | String SKU |
| **MARKETPLACE** (`source=MARKETPLACE`) | DummyJSON external API | String-encoded integer |

Unified products are served at `GET /api/products/unified`. Individual lookup at `GET /api/products/unified/{id}` tries AEM first, then DummyJSON for numeric IDs.

### Semantic search pipeline

```
catalog-service ──Kafka──▶ product-updates topic ──▶ ingestion-worker
                                                           │
                                          SentenceTransformer (all-MiniLM-L6-v2)
                                                           │
                                                       search-db (pgvector)
                                                     search_index table
                                                           │
                                                    search-service (FastAPI)
                                                    GET /search?q=...
```

**`search_index` schema (one row per product):**
- `product_id TEXT PRIMARY KEY`
- `embedding VECTOR(384)` — HNSW index (cosine similarity)
- `search_text TEXT` — GIN tsvector index for full-text search
- `denormalized_doc JSONB` — complete product card data (no follow-up hydration needed)
- `price_amount`, `currency`, `in_stock`, `updated_at`

**Hybrid ranking:** Top-100 vector candidates (HNSW) joined with full-text candidates (GIN). Final score = `vector_score × 0.7 + text_score × 0.3`.

**Kafka event types (topic: `product-updates`):**
- `FULL_UPDATE` — rebuilds doc + embedding. Absent `eventType` defaults to `FULL_UPDATE` (backward-compatible with catalog-service publishing plain `UnifiedProductDTO`).
- `PRICE_UPDATE` — patches price/stock fields via `jsonb_set`; skips embedding regeneration.

Dead-letter queue: `product-updates.DLQ` for events that fail DB writes after retries.

### Search cache pipeline (Phases 1–4)

The search-service implements a 4-layer cache pipeline. Each layer is checked in order; a miss falls through to the next.

```
L1 (in-process dict, 2 min TTL, max 500 entries)
  → L2 (Postgres query_cache, exact key match, soft 10 min / hard 60 min TTL)
      → Lexical-near (Phase 2, pg_trgm trigram similarity)
          → Semantic cache (Phase 3, pgvector cosine similarity)
              → Hybrid product search (live — 70% vector + 30% FTS)
                  → cache write (ACTIVE, soft + hard expiry)
                  → hydrated response (current denormalized_doc bulk-fetched from search_index)
```

On every cache hit, the service **re-hydrates** current `denormalized_doc` rows from `search_index` in a single bulk query — product IDs, not response blobs, are the cache unit.

#### Phase 1 — Exact L1 / L2 cache

Cache key: `SHA-256(normalized_query | filter_hash | sort_key | page_number | page_limit)`

| Layer | Storage | TTL |
|---|---|---|
| L1 | Python in-process `dict` | 2 min monotonic; evict oldest 10 % when 500-entry cap is reached |
| L2 | `query_cache` table (Postgres) | soft 10 min (ACTIVE window) / hard 60 min (absolute barrier) |

#### Phase 2 — Lexical-near cache

When there is no exact L2 match, the service looks for a "close enough" prior query using `pg_trgm`:

1. `pg_trgm` similarity ≥ 0.76
2. Incoming query has ≥ 2 significant tokens (after stopword removal)
3. ≥ 2 significant tokens in common with the candidate
4. `filter_hash`, `sort_key`, `page_number`, `page_limit` match exactly
5. Candidate `hard_expires_at > now()` and `freshness_status != 'HARD_EXPIRED'`

#### Phase 3 — Semantic cache

When there is no lexical-near match, the query embedding is computed and `query_cache` is scanned by cosine similarity:

| Band | Similarity | Extra guards |
|---|---|---|
| Strong accept | ≥ 0.88 | None |
| Borderline | 0.84 – 0.88 | Price-intent conflict check (budget vs premium terms) + token-overlap guardrails |
| Hard reject | < 0.84 | Falls through to live hybrid search |

#### Phase 4 — TTL freshness + event-driven invalidation

**Two-level freshness model:**

| State | Condition | Serving policy |
|---|---|---|
| `ACTIVE` | `now < soft_expires_at` | Served normally |
| `SOFT_EXPIRED` | `soft_expires_at ≤ now < hard_expires_at`, OR minor product event (price / inventory / promo) | Served immediately; background refresh triggered async after response |
| `HARD_EXPIRED` | `now ≥ hard_expires_at`, OR `FULL_UPDATE` with core field change (`title`, `search_text`, `brand`, `category`) | Never served; falls through to live search |

**Event-driven invalidation:**

```
POST /internal/invalidate  {"product_id":"sku-123","event_type":"PRICE_UPDATE"}
```

| `event_type` | Target freshness |
|---|---|
| `PRICE_UPDATE` | `SOFT_EXPIRED` |
| `INVENTORY_UPDATE` | `SOFT_EXPIRED` |
| `PROMOTION_UPDATE` | `SOFT_EXPIRED` |
| `FULL_UPDATE` (non-core fields) | `SOFT_EXPIRED` |
| `FULL_UPDATE` + core field change | `HARD_EXPIRED` |

**L1 coherence via PostgreSQL LISTEN/NOTIFY:**
On invalidation, `pg_notify('search_cache_invalidation', payload_json)` is emitted. A daemon thread in search-service LISTENs and evicts matching L1 entries — no Redis required.

**Background refresh:**
`SOFT_EXPIRED` hits trigger an async refresh via FastAPI `BackgroundTasks`. Each refresh opens its own transient connection to avoid contention with the main `db_conn`.

#### `query_cache` table (Phase 1–4 columns)

| Column | Phase | Notes |
|---|---|---|
| `query_hash`, `filter_hash`, `sort_key`, `page_number`, `page_limit` | 1 | Composite unique cache key |
| `normalized_query`, `ordered_product_ids`, `result_count`, `response_meta` | 1 | |
| `expires_at` | 1 | Legacy field; now mirrors `hard_expires_at` |
| `hit_count`, `last_hit_at` | 1 | LRU analysis |
| `lexical_signature`, `query_tokens`, `cache_version` | 2 | Trigram matching |
| `query_embedding` (VECTOR 384) | 3 | NULL for pre-Phase-3 rows |
| `semantic_cache_enabled`, `semantic_source_query`, `semantic_similarity`, `semantic_meta` | 3 | Semantic match debug |
| `soft_expires_at`, `hard_expires_at`, `freshness_status` | 4 | Two-level TTL model |
| `invalidation_reason`, `invalidated_at`, `last_refresh_at` | 4 | Audit |
| `affected_product_ids` TEXT[] | 4 | GIN-indexed; used for per-product invalidation queries |

**Key indexes:**

| Index | Type | Purpose |
|---|---|---|
| `query_cache_exact_key_idx` | Unique B-tree | Exact cache lookup |
| `query_cache_normalized_query_trgm_idx` | GIN (pg_trgm) | Lexical-near candidates (Phase 2) |
| `query_cache_product_ids_gin_idx` | GIN | Product-level invalidation (Phase 1) |
| `query_cache_affected_product_ids_gin_idx` | GIN | Per-product invalidation (Phase 4) |
| `query_cache_freshness_status_idx` | B-tree | Freshness filtering (Phase 4) |
| `query_cache_hard_expires_at_idx` | B-tree | Hard-expiry cleanup (Phase 4) |

> **HNSW semantic index (Phase 3):** Commented out in `init.sql`. Enable when `query_cache` regularly exceeds ~10k active rows and `sem_lookup_ms` latency appears in logs.

### Search API

#### `GET /search?q=<query>&limit=<n>`

Returns hydrated product results with cache metadata. Public — no JWT required.

```json
{
  "query": "running shoes",
  "results": [ { "product_id": "...", "title": "...", "price": {...}, "in_stock": true } ],
  "result_count": 5,
  "cache_hit": "L1 | L2 | LEXICAL_NEAR | SEMANTIC | MISS",
  "freshness_status": "ACTIVE | SOFT_EXPIRED",
  "meta": {}
}
```

#### `POST /internal/invalidate`

Internal endpoint — not exposed through nginx or the API gateway.

```json
// Request
{ "product_id": "sku-123", "event_type": "PRICE_UPDATE", "changed_fields": [] }

// Response
{ "product_id": "sku-123", "event_type": "PRICE_UPDATE", "target_status": "SOFT_EXPIRED", "rows_updated": 14 }
```

#### `GET /cache/stats`

Returns all 9 Phase-4 cache metrics plus TTL configuration:

```json
{
  "l1_size": 12, "l1_max": 500, "l1_ttl_seconds": 120,
  "l2_soft_ttl_seconds": 600, "l2_hard_ttl_seconds": 3600,
  "hits": { "l1": 0, "l2": 0, "lexical_near": 0, "semantic": 0 },
  "misses": 0,
  "active_cache_hits": 0, "soft_expired_cache_hits": 0, "hard_expired_rejects": 0,
  "refresh_triggers": 0, "refresh_successes": 0, "refresh_failures": 0,
  "invalidation_events": 0, "invalidated_rows": 0, "l1_evictions_from_notify": 0
}
```

### Frontend search (Header)
- 300ms debounced input + AbortController (cancels in-flight requests on each keystroke)
- Results rendered as an inline dropdown with title and formatted price from `denormalized_doc`
- Clicking a result uses React Router `<Link to>` for client-side navigation (preserves state, avoids full-page reload)
- No follow-up catalog-service fetch per result — all card data is in `denormalized_doc`

### Database-per-service
Each stateful service owns its Postgres instance. No cross-database foreign keys — `cart_items` references users by `user_email` string.

| DB | Service | Key tables |
|---|---|---|
| auth-db (:5433) | auth-service | `credentials` |
| user-db (:5434) | user-service | `user_profiles` |
| cart-db (:5435) | cart-service | `cart_items` |
| search-db (:5436) | search-service + ingestion-worker | `search_index` (pgvector) |

## Cloud-Readiness (12-Factor)

| Factor | Status | Detail |
|---|---|---|
| Config Externalization | ✅ | All secrets via `${ENV_VAR}`, no hardcoded values |
| Graceful Shutdown | ✅ | `server.shutdown=graceful` + 30s phase timeout on all services |
| K8s Health Probes | ✅ | `/actuator/health/liveness` and `/actuator/health/readiness` on all Spring services |
| Non-root containers | ✅ | All Dockerfiles run as `appuser` (system account) |
| STDOUT logging | ✅ | Spring Boot default; no file appenders |
| Stateless services | ✅ | JWT auth, no sticky sessions, no local filesystem writes |

### K8s probe configuration (example)
```yaml
livenessProbe:
  httpGet:
    path: /actuator/health/liveness
    port: 8081
  initialDelaySeconds: 30
  periodSeconds: 10
readinessProbe:
  httpGet:
    path: /actuator/health/readiness
    port: 8081
  initialDelaySeconds: 20
  periodSeconds: 5
```

## AWS deployment (ECS Fargate)

Each microservice becomes its own ECS task definition. General pattern:

1. Create separate RDS instances (or schemas) for auth, user, cart, and search databases.
2. Store DB credentials and `JWT_SECRET` in AWS Secrets Manager.
3. Build and push each service image to ECR:
   ```bash
   mvn clean install -DskipTests
   docker build -t hopnshoppe-auth-service ./auth-service
   # tag + push to ECR
   ```
4. Create ECS task definitions with env vars mapped from Secrets Manager.
5. Create an ALB with target groups for each service. Health check path: `/actuator/health`.
6. Use ECS service discovery or AWS Cloud Map for inter-service communication.
7. Deploy `search-service` and `ingestion-worker` as separate ECS tasks; use Amazon MSK for Kafka and RDS with the `pgvector` extension for `search-db`.

### Frontend (S3 + CloudFront)
1. Build: `cd caas-frontend && npm run build`
2. Upload `dist/` to an S3 bucket.
3. Create a CloudFront distribution with:
   - Default origin: S3 bucket (OAC/OAI)
   - `/api/*` behavior: origin = ALB (api-gateway), caching disabled
   - `/api/search/*` behavior: origin = ALB (search-service), caching disabled

## Local dev
```bash
# Run a single Spring service without Docker (example: cart-service)
cd cart-service
SPRING_DATASOURCE_PASSWORD=password ./mvnw spring-boot:run

# Frontend hitting the gateway directly
cd caas-frontend
VITE_API_BASE=http://localhost:8080/api npm run dev

# Run search-service locally
cd search-service
pip install -r requirements.txt
SEARCH_DB_PASSWORD=password uvicorn main:app --port 8085

# Run ingestion-worker locally
cd ingestion-worker
pip install -r requirements.txt
SEARCH_DB_PASSWORD=password KAFKA_BOOTSTRAP_SERVERS=localhost:9092 python main.py
```

## Known limitations & Phase 5 candidates

These are architectural gaps identified during development. None are implemented yet.

| Area | Issue | Suggested fix |
|---|---|---|
| **Thread safety** | `db_conn` is a single shared `psycopg2` connection; not thread-safe under concurrent FastAPI workers | Migrate to `psycopg2.pool.ThreadedConnectionPool` |
| **Semantic HNSW index** | Phase 3 uses exact cosine scan on `query_cache` (no ANN index) | Enable HNSW index on `query_embedding` when table exceeds ~10k active rows |
| **Adaptive TTL** | Soft/hard windows are fixed constants | Drive TTL from `hit_count` or time-of-day popularity signals |
| **Brand/category conflict detection** | Semantic cache guards against price-intent conflicts but not brand or category conflicts | Add conflict term sets for brand names and categories |
| **Embedding backfill** | Rows written before Phase 3 have `query_embedding = NULL` and are excluded from semantic scan | One-time migration script using batch embed |
| **Search gateway routing** | `search-service` uses a direct URI (`http://search-service:8085`) instead of `lb://` through Eureka | Register with Eureka for load-balanced routing |
| **Automated Kafka → invalidation bridge** | `POST /internal/invalidate` is called manually; no automated bridge from Kafka product-updates events | Kafka consumer in search-service (or sidecar) to auto-invalidate on upstream events |
| **Query cache size cap** | `query_cache` has no row-count ceiling; only TTL-based cleanup | Periodic job to cap at a max row count, evicting by `last_hit_at` |

## Security notes
- Never commit `.env`, API keys, or JWT secrets.
- `JWT_SECRET` must be the same value across api-gateway, auth-service, user-service, and cart-service.
- Internal endpoints (`/internal/**` on user-service) are only reachable on the Docker/K8s network — not exposed through nginx or the API gateway.
- `GET /api/search/**` is a public path (no JWT required) — do not expose sensitive product data through search results.
- Rotate all secrets before any public deployment.

## Flyway migrations
Each service with a database manages its own schema independently:
- `auth-service/src/main/resources/db/migration/` — `credentials` table
- `user-service/src/main/resources/db/migration/` — `user_profiles` table
- `cart-service/src/main/resources/db/migration/` — `cart_items` table
- `search-service/init.sql` — `search_index` table (mounted into search-db via Docker entrypoint, not Flyway)
