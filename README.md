# hopnshoppe

A small e-commerce demo stack:

- **config-server**: Spring Cloud Config server (port 8888) serving configs from `config-server/config-repo`.
- **config-client**: Spring Boot backend (port 8081) fetching product data (GraphQL) and handling auth/account with Postgres.
- **proxy**: Node/Express proxy (port 3000) forwarding product requests to the backend with CORS enabled.
- **frontend**: React/Vite SPA built and served by nginx (port 5173).

## Prerequisites
- Docker + Docker Compose
- Ports available: 5432, 8888, 8081, 3000, 5173 (adjust in `docker-compose.yml` if needed).
- A `.env` file with your secrets (use `.env.example` as a template). Keep `.env` out of git.

## Environment variables
Create `.env` in the repo root (do not commit it):
```
POSTGRES_DB=hopnshoppe
POSTGRES_USER=postgres
POSTGRES_PASSWORD=replace_me_with_strong_password

SPRING_DATASOURCE_PASSWORD=${POSTGRES_PASSWORD}

API_KEY=replace_me_with_api_key
TARGET_URL=http://config-client:8081/products
BACKEND_BASE=http://config-client:8081

# Optional:
# JWT_SECRET=replace_me_with_long_random_secret
# GRAPHQL_ENDPOINT=http://host.docker.internal:8080/content/cq:graphql/wknd/endpoint.json
# SPRING_DATASOURCE_URL=jdbc:postgresql://<rds-endpoint>:5432/<db>
# SPRING_DATASOURCE_USERNAME=<db-user>
# SPRING_DATASOURCE_PASSWORD=<db-pass>
# SPRING_PROFILES_ACTIVE=prod
```

`docker-compose.yml` references these variables and will fail fast if required ones are missing.

## Quick start (Docker Compose)
From repo root:
```bash
docker compose up -d --build
```

Services:
- Postgres: localhost:5432
- Config server: http://localhost:8888/config-client.yml
- Backend: http://localhost:8081/products
- Frontend: http://localhost:5173 (nginx proxies `/api/*` to backend inside Compose)

Profiles:
- Default is `local` (set in `application.yml`). For cloud/RDS, run the jar with `-Dspring.profiles.active=prod` and pass `SPRING_DATASOURCE_URL`, `SPRING_DATASOURCE_USERNAME`, `SPRING_DATASOURCE_PASSWORD`.

Logs:
```bash
docker compose logs -f <service>
# e.g., docker compose logs -f config-client
```

## Frontend routing
Client-side routing is served via nginx with SPA fallback (`caas-frontend/nginx.conf`), so deep links like `/products` or `/login` work.

## Local dev (optional)
- Backend:
  ```bash
  cd config-client
  ./mvnw spring-boot:run
  ```
  If running on host, set `spring.datasource.url=jdbc:postgresql://localhost:5432/${POSTGRES_DB}` and export `SPRING_DATASOURCE_PASSWORD`.

- Frontend:
  ```bash
  cd caas-frontend
  npm install
  # default: use /api; for local dev hitting backend directly set VITE_API_BASE=http://localhost:8081 VITE_API_ROOT=http://localhost:8081
  npm run dev
  ```

## Config locations
- Backend config served from `config-server/config-repo/config-client.yml` (API key, target URL, GraphQL endpoint).
- Database schema managed by Flyway (migrations in `config-client/src/main/resources/db/migration`).

## Flyway migrations
- Initial schema: `V1__init.sql` creates `users` and `cart_items`.
- `spring.jpa.hibernate.ddl-auto` is set to `validate` in profile-specific configs; Flyway handles migrations.

## Security notes
- Do not commit real passwords, API keys, or JWT secrets. Keep them in `.env` (already gitignored).
- Replace placeholder values in `.env` before running.
- Rotate secrets for any public deployments.
