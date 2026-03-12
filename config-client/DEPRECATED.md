# DEPRECATED — Legacy Monolith

This module is **inactive** and must not be run in any environment.

## Status

| Item | State |
|---|---|
| Maven reactor build | Excluded (not listed in root `pom.xml` modules) |
| Docker Compose | Removed — no service definition exists |
| Runtime database | Removed — `postgres` / `pgdata-hopnshoppe` volume dropped |

## Why it was replaced

`config-client` was the original HopNShoppe monolith. It has been decomposed into the following independently deployable microservices:

| Responsibility | Replacement service |
|---|---|
| Authentication / JWT issuance | `auth-service` (port 8081) |
| User profile management | `user-service` (port 8084) |
| Product catalogue | `catalog-service` (port 8083) |
| Cart management | `cart-service` (port 8082) |

## Source code retention

The source files (`.java`, `.xml`, resource files) are kept here for historical reference and to aid understanding of the migration. They must not be compiled into the production build or started as a container.

## Do not

- Add this module back to the root `pom.xml` `<modules>` section
- Add a `config-client` service back to `docker-compose.yml`
- Use the `postgres` / `pgdata-hopnshoppe` database for any new work
