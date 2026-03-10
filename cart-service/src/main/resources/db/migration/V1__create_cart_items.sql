-- cart_items: user_email replaces the old cross-database FK to users.id.
-- The unique constraint prevents duplicate SKUs per user.
CREATE TABLE cart_items (
    id        BIGSERIAL PRIMARY KEY,
    user_email VARCHAR(255) NOT NULL,
    sku        VARCHAR(255) NOT NULL,
    quantity   INTEGER      NOT NULL DEFAULT 1,
    CONSTRAINT uq_user_sku UNIQUE (user_email, sku)
);
