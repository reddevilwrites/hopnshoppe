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

## Cloud-Readiness (12-Factor)
All services are configured for cloud/K8s deployment:
- **Graceful shutdown**: `server.shutdown=graceful` + 30s phase timeout on every service
- **K8s health probes**: `management.endpoint.health.probes.enabled=true` exposes `/actuator/health/liveness` and `/actuator/health/readiness` on every service
- **Non-root containers**: All Dockerfiles create and switch to `appuser` (system account, no login shell)
- **Config externalization**: All secrets via `${ENV_VAR}` — no hardcoded values
- **STDOUT logging**: Spring Boot default logging; no file appenders
- **Stateless services**: JWT-based auth, no session state, no local filesystem writes
