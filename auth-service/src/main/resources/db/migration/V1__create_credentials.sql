-- Stores authentication credentials only.
-- Profile data (first_name, last_name, phone) lives in user-service/user_db.
-- There is intentionally NO foreign key to user_db — database-per-service forbids cross-DB FKs.

CREATE TABLE IF NOT EXISTS credentials (
    id            BIGSERIAL    PRIMARY KEY,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_credentials_email ON credentials (email);
