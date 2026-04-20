# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HopNShoppe is a full-stack e-commerce application built on a **microservices architecture**. The backend is decomposed into independently deployable Spring Boot services coordinated via a Spring Cloud Config server and Eureka service registry, with a React/Vite frontend served by nginx — all orchestrated via Docker Compose.

## Build & Run Commands

### Full stack (Docker Compose)
```bash
# Build all JARs first, then start containers
mvn clean install -DskipTests
docker compose up -d --build        # build images and start all services
docker compose logs -f <service>    # tail logs for any service
docker compose down                 # stop all services
```

### Rebuild a single service after a code change
```bash
mvn clean install -DskipTests -pl <module> -am
docker compose up -d --no-deps --build <service-name>
```

### Individual service (local dev, no Docker)
```bash
cd <service-dir>
./mvnw spring-boot:run
./mvnw package
./mvnw test
./mvnw test -Dtest=ClassName
./mvnw test -Dtest=ClassName#method
```

### Frontend (caas-frontend)
```bash
cd caas-frontend
npm install
npm run dev                         # dev server on :5173
npm run build                       # production build to dist/
npm run lint                        # ESLint
npm run preview                     # preview production build
```
For local dev hitting the API gateway directly: `VITE_API_BASE=http://localhost:8080/api npm run dev`

## Architecture

### Service topology
| Service | Port | Role |
|---|---|---|
| **discovery-server** | 8761 | Eureka service registry |
| **config-server** | 8888 | Spring Cloud Config server |
| **api-gateway** | 8080 | Spring Cloud Gateway — JWT validation, routing |
| **auth-service** | 8081 | Login / signup / JWT issuance |
| **user-service** | 8084 | User profile management |
| **cart-service** | 8082 | Cart state; calls catalog-service for product enrichment |
| **catalog-service** | 8083 | Stateless GraphQL proxy to AEM CMS |
| **frontend** | 5173→80 | React 19 SPA served by nginx |
| **auth-db** | 5433 | PostgreSQL — `auth_db` (credentials table) |
| **user-db** | 5434 | PostgreSQL — `user_db` (user_profiles table) |
| **cart-db** | 5435 | PostgreSQL — `cart_db` (cart_items table) |

### Request flow
```
Browser → nginx (:5173) → /api/* → api-gateway (:8080) → lb://service → service
                         → /content/* → AEM dispatcher (host.docker.internal:8090)
```
JWT validation happens at the gateway. Public paths (`/api/auth/**`, `/api/products/**`, `/actuator`) bypass JWT checks.

### Inter-service calls
| Caller | Callee | Endpoint | When |
|---|---|---|---|
| auth-service | user-service | `POST /internal/users` | During signup (compensating rollback on failure) |
| cart-service | catalog-service | `GET /products/{sku}` | Enriching cart DTOs with product data |

### Package structure (per service)
```
com.hopnshoppe.<service>/
  controller/   — REST endpoints
  service/      — Business logic (+ inter-service REST clients)
  repository/   — Spring Data JPA repositories
  model/        — JPA entities
  dto/          — Request/response DTOs
  filter/       — JwtFilter (validates JWT on protected endpoints)
  config/       — SecurityConfig
  util/         — JwtUtil
```
catalog-service has no DB layer — controller → service → GraphQL only.

### Security
- `api-gateway` validates JWTs on every protected request via `JwtAuthenticationFilter`
- Public paths: `/api/auth/**`, `/api/products/**`, `/actuator`
- JWT `sub` = user email — the cross-service user identifier
- `JWT_SECRET` env var shared across api-gateway, auth-service, user-service, cart-service
- Internal endpoints (`/internal/**` on user-service) are not exposed through nginx

### Frontend structure (`caas-frontend`)
- `src/api.js` — API base URL config (`VITE_API_BASE` env var, defaults to `/api`)
- `src/App.jsx` — React Router routes
- `src/components/pages/` — Login, Signup, ProductList, ProductDetail, Cart, Checkout, Account, Home
- `src/components/Header.jsx` — Shared navigation header
- JWT stored in `sessionStorage`

### Database
- Database-per-service pattern; no cross-DB foreign keys
- All schemas managed by Flyway migrations (`db/migration/V{n}__{description}.sql`)
- `ddl-auto=validate` — Hibernate validates, never modifies schema
- `cart_items.user_email` (String) replaces old FK to `users.id`

### Configuration
- Centralized config served from `config-server/config-repo/<service-name>.yml`
- All secrets injected via env vars (`JWT_SECRET`, `POSTGRES_PASSWORD`, etc.)
- No hardcoded secrets in YAML or properties files

## Key Conventions
- Lombok (`@Data`, `@Builder`, etc.) — minimal boilerplate in entities/DTOs
- Flyway migration naming: `V{n}__{description}.sql`
- Frontend uses Tailwind CSS v4 (Vite plugin, `@import "tailwindcss"` in index.css)
- Frontend API calls go through nginx `/api` in Docker; override with `VITE_API_BASE` for local dev

## Observability

This document describes the observability stack currently implemented in this repository. It is intended to let any future agent find the right service, port, endpoint, config file, and dashboard without having to rediscover the setup.

### Summary

The project uses an OTLP-first observability stack with these components:

- OpenTelemetry Collector for trace ingest
- Tempo for trace storage
- Prometheus for metrics scraping
- Loki for log storage
- Promtail for Docker log shipping
- Grafana for dashboards and alerting
- cAdvisor for container-level CPU and memory metrics

Jaeger is not part of the current runtime stack.

### Host Ports

#### Application and infrastructure ports

These are the main non-observability services and should remain stable:

- `8080` API Gateway
- `8081` auth-service
- `8082` cart-service
- `8083` catalog-service
- `8084` user-service
- `8085` search-service
- `8761` discovery-server
- `8888` config-server
- `9092` Kafka
- `5173` frontend
- `5433` user-db
- `5434` auth-db
- `5435` cart-db
- `5436` search-db

#### Observability ports

- `3000` Grafana
- `3100` Loki
- `3200` Tempo
- `4317` OTLP gRPC ingest on the collector
- `4318` OTLP HTTP ingest on the collector
- `9090` Prometheus

### Docker Services

Observability-related services are defined in [docker-compose.yml](./docker-compose.yml:1).

#### Collector and storage

- `otel-collector`
  - Container name: `hopnshoppe-otel-collector`
  - Purpose: central OTLP ingest for traces
  - Host ports: `4317`, `4318`
  - Config: [observability/otel-collector/config.yaml](./observability/otel-collector/config.yaml:1)

- `tempo`
  - Container name: `hopnshoppe-tempo`
  - Purpose: trace backend
  - Host port: `3200`
  - Config: [observability/tempo/tempo.yaml](./observability/tempo/tempo.yaml:1)

- `prometheus`
  - Container name: `hopnshoppe-prometheus`
  - Purpose: scrape and store metrics
  - Host port: `9090`
  - Config: [observability/prometheus/prometheus.yml](./observability/prometheus/prometheus.yml:1)
  - Alert rules: [observability/prometheus/alerts.yml](./observability/prometheus/alerts.yml:1)

- `loki`
  - Container name: `hopnshoppe-loki`
  - Purpose: log backend
  - Host port: `3100`
  - Config: [observability/loki/config.yaml](./observability/loki/config.yaml:1)

- `promtail`
  - Container name: `hopnshoppe-promtail`
  - Purpose: scrape Docker logs and send them to Loki
  - Uses Docker socket
  - Config: [observability/promtail/config.yml](./observability/promtail/config.yml:1)

- `grafana`
  - Container name: `hopnshoppe-grafana`
  - Purpose: dashboards, traces, logs, alerting UI
  - Host port: `3000`
  - Default credentials: `admin / admin`
  - Provisioning directory: [observability/grafana/provisioning](./observability/grafana/provisioning:1)
  - Dashboard directory: [observability/grafana/dashboards](./observability/grafana/dashboards:1)

- `cadvisor`
  - Container name: `hopnshoppe-cadvisor`
  - Purpose: container CPU, memory, filesystem, and runtime metrics
  - Scraped internally by Prometheus at `cadvisor:8080`

### UI Locations

#### Grafana

- URL: `http://localhost:3000`
- Login: `admin / admin`

Dashboards are provisioned under the `HopnShoppe` folder.

- Folder URL: `http://localhost:3000/dashboards/f/efjkqy9e853b4f/hopnshoppe`
- Overview dashboard: `http://localhost:3000/d/hopnshoppe-overview/hopnshoppe-overview`
- JVM dashboard: `http://localhost:3000/d/hopnshoppe-jvm/hopnshoppe-jvm-services`
- Containers dashboard: `http://localhost:3000/d/hopnshoppe-containers/hopnshoppe-containers`
- Search dashboard: `http://localhost:3000/d/hopnshoppe-search/hopnshoppe-search-and-ingestion`

#### Prometheus

- URL: `http://localhost:9090`

#### Loki

- Readiness endpoint: `http://localhost:3100/ready`

### Telemetry by Service

#### Spring Boot services

These services expose Prometheus metrics on `/actuator/prometheus` and are scraped by Prometheus under the `spring-services` job:

- `api-gateway` at `http://localhost:8080/actuator/prometheus`
- `auth-service` at `http://localhost:8081/actuator/prometheus`
- `cart-service` at `http://localhost:8082/actuator/prometheus`
- `catalog-service` at `http://localhost:8083/actuator/prometheus`
- `user-service` at `http://localhost:8084/actuator/prometheus`

These services also expose:

- `/actuator/health`
- `/actuator/info`

Tracing for these services is configured to export to the collector with:

- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://otel-collector:4318/v1/traces`

Micrometer `application` tag is enabled so Grafana dashboards can query by service name.

Expected `application` values:

- `api-gateway`
- `auth-service`
- `cart-service`
- `catalog-service`
- `user-service`

Percentile histogram buckets are enabled for HTTP server requests so the JVM dashboard can compute p95 latency:

```yaml
management:
  metrics:
    distribution:
      percentiles-histogram:
        http.server.requests: true
```

This emits `http_server_requests_seconds_bucket` alongside the default `_count`, `_sum`, and `_max` series. Without this setting, `histogram_quantile()` queries return no data.

#### search-service

- App URL: `http://localhost:8085`
- Health endpoint: `http://localhost:8085/health`
- Metrics endpoint: `http://localhost:8085/metrics`
- Compatibility endpoint kept in place: `http://localhost:8085/cache/stats`

Tracing is configured with:

- `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318`
- `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`
- `OTEL_SERVICE_NAME=search-service`

Metrics include search latency, cache hit rate, cache size, and search event counters.

#### ingestion-worker

- No host port is published for the worker itself
- Metrics are exposed internally on `ingestion-worker:9108/metrics`
- Prometheus scrapes that internal metrics endpoint

Tracing is configured with:

- `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318`
- `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`
- `OTEL_SERVICE_NAME=ingestion-worker`

Metrics include ingestion event counters and database connectivity state.

#### Logs

Application logs remain on stdout and are scraped from Docker by Promtail.

Source path:

- Docker socket-based discovery via [observability/promtail/config.yml](./observability/promtail/config.yml:1)

Destination:

- Loki at `http://loki:3100`

Current log labels include:

- `container`
- `service`
- `stream`

### Prometheus Scrape Jobs

Configured in [observability/prometheus/prometheus.yml](./observability/prometheus/prometheus.yml:1).

Current jobs:

- `otel-collector`
  - Target: `otel-collector:8889`
- `cadvisor`
  - Target: `cadvisor:8080`
- `spring-services`
  - Metrics path: `/actuator/prometheus`
  - Targets:
    - `api-gateway:8080`
    - `auth-service:8081`
    - `cart-service:8082`
    - `catalog-service:8083`
    - `user-service:8084`
- `search-service`
  - Metrics path: `/metrics`
  - Target: `search-service:8085`
- `ingestion-worker`
  - Metrics path: `/metrics`
  - Target: `ingestion-worker:9108`

### Grafana Datasources

Configured in [observability/grafana/provisioning/datasources/datasources.yml](./observability/grafana/provisioning/datasources/datasources.yml:1).

Provisioned datasources:

- `Prometheus`
  - UID: `prometheus`
  - URL: `http://prometheus:9090`
  - Default datasource
- `Loki`
  - UID: `loki`
  - URL: `http://loki:3100`
- `Tempo`
  - UID: `tempo`
  - URL: `http://tempo:3200`

Tempo is configured with traces-to-logs and service map integration back to Loki and Prometheus.

### Grafana Dashboards

Provisioning file:

- [observability/grafana/provisioning/dashboards/dashboards.yml](./observability/grafana/provisioning/dashboards/dashboards.yml:1)

Dashboard JSON files:

- [observability/grafana/dashboards/hopnshoppe-overview.json](./observability/grafana/dashboards/hopnshoppe-overview.json:1)
- [observability/grafana/dashboards/hopnshoppe-jvm.json](./observability/grafana/dashboards/hopnshoppe-jvm.json:1)
- [observability/grafana/dashboards/hopnshoppe-containers.json](./observability/grafana/dashboards/hopnshoppe-containers.json:1)
- [observability/grafana/dashboards/hopnshoppe-search.json](./observability/grafana/dashboards/hopnshoppe-search.json:1)

Dashboard intent:

- `HopnShoppe Overview`
  - high-level app health
  - Spring request rate
  - search cache hit rate
  - search latency
- `HopnShoppe JVM Services`
  - heap usage
  - process CPU usage
  - Spring HTTP p95 latency
- `HopnShoppe Containers`
  - container CPU usage
  - container memory working set
- `HopnShoppe Search and Ingestion`
  - search cache hit rate
  - L1 cache size
  - search p95 latency
  - search event rates
  - ingestion worker event rates
  - ingestion DB connectivity

### Alerting

#### Prometheus rules

Prometheus alert definitions are stored in:

- [observability/prometheus/alerts.yml](./observability/prometheus/alerts.yml:1)

Current alert coverage includes:

- service scrape target down
- high 5xx error rate
- search cache miss spike
- search p95 latency high
- ingestion worker database disconnected

#### Grafana alert provisioning

Grafana alert provisioning files:

- [observability/grafana/provisioning/alerting/rules.yml](./observability/grafana/provisioning/alerting/rules.yml:1)
- [observability/grafana/provisioning/alerting/policies.yml](./observability/grafana/provisioning/alerting/policies.yml:1)
- [observability/grafana/provisioning/alerting/contact-points.yml](./observability/grafana/provisioning/alerting/contact-points.yml:1)

### Where to Edit What

#### If traces are broken

Check these files first:

- [observability/otel-collector/config.yaml](./observability/otel-collector/config.yaml:1)
- [observability/tempo/tempo.yaml](./observability/tempo/tempo.yaml:1)
- [docker-compose.yml](./docker-compose.yml:1)

#### If Spring Boot metrics are broken

Check these files first:

- [observability/prometheus/prometheus.yml](./observability/prometheus/prometheus.yml:1)
- [api-gateway/src/main/resources/application.yml](./api-gateway/src/main/resources/application.yml:1)
- [auth-service/src/main/resources/application.yml](./auth-service/src/main/resources/application.yml:1)
- [cart-service/src/main/resources/application.yml](./cart-service/src/main/resources/application.yml:1)
- [catalog-service/src/main/resources/application.yml](./catalog-service/src/main/resources/application.yml:1)
- [user-service/src/main/resources/application.yml](./user-service/src/main/resources/application.yml:1)

#### If Python metrics are broken

Check these files first:

- [search-service/main.py](./search-service/main.py:1)
- [search-service/requirements.txt](./search-service/requirements.txt:1)
- [ingestion-worker/main.py](./ingestion-worker/main.py:1)
- [ingestion-worker/requirements.txt](./ingestion-worker/requirements.txt:1)

#### If logs are broken

Check these files first:

- [observability/loki/config.yaml](./observability/loki/config.yaml:1)
- [observability/promtail/config.yml](./observability/promtail/config.yml:1)
- [observability/grafana/provisioning/datasources/datasources.yml](./observability/grafana/provisioning/datasources/datasources.yml:1)

#### If dashboards are broken

Check these files first:

- [observability/grafana/provisioning/dashboards/dashboards.yml](./observability/grafana/provisioning/dashboards/dashboards.yml:1)
- [observability/grafana/dashboards](./observability/grafana/dashboards:1)

### Current Known Notes

- Spring Boot metrics are expected on `/actuator/prometheus` for the five Java services listed above.
- The Grafana JVM dashboard depends on the `application` label being present on Micrometer metrics.
- The JVM dashboard HTTP p95 Latency panel requires `http_server_requests_seconds_bucket` metrics. These are emitted only when `management.metrics.distribution.percentiles-histogram.http.server.requests: true` is set — this is now configured in every Spring Boot service's `application.yml`.
- Search and ingestion metrics are Prometheus-native endpoints, not actuator endpoints.
- OTLP traces should always be sent to the collector, not directly to Tempo.
- Logs are expected to remain on stdout and be scraped by Promtail.

### Embedding Model Change Policy

Any change to the embedding model used by `search-service` or `ingestion-worker` must be treated as a data migration, not just a configuration change.

- A new embedding model produces a new vector space. Existing semantic-cache embeddings and stored search embeddings are no longer safely comparable to newly generated vectors.
- When `EMBED_MODEL` changes, plan for full semantic cache invalidation and search-index embedding rebuild before treating the system as healthy.
- Minimum required actions for an embedding-model change:
  - invalidate `query_cache` semantic entries, including stored `query_embedding` values
  - rebuild or repopulate `search_index.embedding`
  - replay `FULL_UPDATE` events through Kafka or run the explicit re-embed path for persisted search rows
  - restart `search-service` and `ingestion-worker` so both services load the same model and re-verify vector dimensions
  - validate that the database vector dimensions, runtime model dimensions, and stored non-null embeddings all match
- Do not assume semantic-cache thresholds remain valid after a model change. Re-run threshold calibration and semantic-match validation using reported production-style data.
- If upstream catalog sources are partially offline during a rebuild, expect replay gaps. Either keep stale rows out of search results or remove orphaned rows that are no longer present in the current source-of-truth replay.

References:
- https://tianpan.co/blog/2026-04-09-semantic-caching-llm-production
- https://portkey.ai/blog/semantic-caching-thresholds/


### Cloud-Readiness (12-Factor)
All services are configured for cloud/K8s deployment:
- **Graceful shutdown**: `server.shutdown=graceful` + 30s phase timeout on every service
- **K8s health probes**: `management.endpoint.health.probes.enabled=true` exposes `/actuator/health/liveness` and `/actuator/health/readiness` on every service
- **Non-root containers**: All Dockerfiles create and switch to `appuser` (system account, no login shell)
- **Config externalization**: All secrets via `${ENV_VAR}` — no hardcoded values
- **STDOUT logging**: Spring Boot default logging; no file appenders
- **Stateless services**: JWT-based auth, no session state, no local filesystem writes
