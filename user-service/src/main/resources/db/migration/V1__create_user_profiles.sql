-- user_profiles owns all non-sensitive user data.
-- Credentials (password hash) live exclusively in auth-service/auth_db.
--
-- email is the canonical cross-service identifier; it is stored here for
-- self-contained profile lookups without calling auth-service.
--
-- NOTE: There is intentionally NO foreign key back to auth-service's
-- credentials table — database-per-service means cross-DB FKs are forbidden.
-- Referential integrity across services is enforced at the application layer.

CREATE TABLE IF NOT EXISTS user_profiles (
    id         BIGSERIAL    PRIMARY KEY,
    email      VARCHAR(255) NOT NULL UNIQUE,
    first_name VARCHAR(50)  NOT NULL,
    last_name  VARCHAR(50)  NOT NULL,
    phone      VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_email ON user_profiles (email);
