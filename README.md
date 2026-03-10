# hopnshoppe

A full-stack e-commerce demo built on a **microservices architecture** with Content-as-a-Service (AEM CMS).

## Services

| Service | Port | Description |
|---|---|---|
| discovery-server | 8761 | Eureka service registry |
| config-server | 8888 | Spring Cloud Config server |
| api-gateway | 8080 | JWT validation + routing |
| auth-service | 8081 | Login / signup / JWT issuance |
| user-service | 8084 | User profile management |
| cart-service | 8082 | Cart state (database-per-service) |
| catalog-service | 8083 | Stateless GraphQL proxy to AEM CMS |
| frontend | 5173→80 | React 19 SPA served by nginx |
| auth-db | 5433 | PostgreSQL — credentials |
| user-db | 5434 | PostgreSQL — user profiles |
| cart-db | 5435 | PostgreSQL — cart items |

## Prerequisites
- Docker + Docker Compose
- Maven 3.9+ (for building JARs)
- Ports available: 5433–5435, 8080–8084, 8761, 8888, 5173
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

Logs:
```bash
docker compose logs -f <service-name>
```

## Architecture

### Request flow
```
Browser → nginx (:5173) ─→ /api/* ─→ api-gateway (:8080) ─→ lb://service → service
                          → /content/* → AEM dispatcher (host.docker.internal:8090)
```

### Inter-service calls
- **auth-service → user-service** (`POST /internal/users`) during signup with compensating rollback
- **cart-service → catalog-service** (`GET /products/{sku}`) for product enrichment

### Database-per-service
Each stateful service owns its Postgres instance. No cross-database foreign keys — `cart_items` references users by `user_email` string.

## Cloud-Readiness (12-Factor)

| Factor | Status | Detail |
|---|---|---|
| Config Externalization | ✅ | All secrets via `${ENV_VAR}`, no hardcoded values |
| Graceful Shutdown | ✅ | `server.shutdown=graceful` + 30s phase timeout on all services |
| K8s Health Probes | ✅ | `/actuator/health/liveness` and `/actuator/health/readiness` enabled on all services |
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

1. Create separate RDS instances (or schemas) for auth, user, and cart databases.
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

### Frontend (S3 + CloudFront)
1. Build: `cd caas-frontend && npm run build`
2. Upload `dist/` to an S3 bucket.
3. Create a CloudFront distribution with:
   - Default origin: S3 bucket (OAC/OAI)
   - `/api/*` behavior: origin = ALB (api-gateway), caching disabled

## Local dev
```bash
# Run a single service without Docker (example: cart-service)
cd cart-service
SPRING_DATASOURCE_PASSWORD=password ./mvnw spring-boot:run

# Frontend hitting the gateway directly
cd caas-frontend
VITE_API_BASE=http://localhost:8080/api npm run dev
```

## Security notes
- Never commit `.env`, API keys, or JWT secrets.
- `JWT_SECRET` must be the same value across api-gateway, auth-service, user-service, and cart-service.
- Internal endpoints (`/internal/**` on user-service) are only reachable on the Docker/K8s network — not exposed through nginx or the API gateway.
- Rotate all secrets before any public deployment.

## Flyway migrations
Each service with a database manages its own schema independently:
- `auth-service/src/main/resources/db/migration/` — `credentials` table
- `user-service/src/main/resources/db/migration/` — `user_profiles` table
- `cart-service/src/main/resources/db/migration/` — `cart_items` table
