-- Enable pgvector extension (provided by ankane/pgvector image).
CREATE EXTENSION IF NOT EXISTS vector;

-- One row per product.  The denormalized_doc stores all fields a search-result
-- card needs, so the frontend never needs a follow-up catalog call per result.
CREATE TABLE IF NOT EXISTS search_index (
    product_id       TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    brand            TEXT,
    search_text      TEXT NOT NULL,
    denormalized_doc JSONB NOT NULL,
    embedding        VECTOR(384) NOT NULL,
    price_amount     NUMERIC(12,2),
    currency         TEXT,
    in_stock         BOOLEAN,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HNSW index for approximate nearest-neighbour vector search (cosine distance).
-- HNSW builds incrementally, requires no minimum row count, and works well
-- for both small dev datasets and large production tables.
CREATE INDEX IF NOT EXISTS idx_search_embedding
    ON search_index USING hnsw (embedding vector_cosine_ops);

-- GIN index over a precomputed tsvector for fast PostgreSQL full-text search.
-- The expression must match the WHERE clause in the hybrid query exactly so
-- the planner can use the index.
CREATE INDEX IF NOT EXISTS idx_search_fts
    ON search_index USING GIN (to_tsvector('english', search_text));

-- ─── Phase 1 exact-cache ────────────────────────────────────────────────────
-- Stores ordered product IDs (not full responses) for exact-query cache hits.
-- On a cache hit, current denormalized_doc rows are bulk-fetched from
-- search_index in one query so returned cards always reflect live data.
CREATE TABLE IF NOT EXISTS query_cache (
    cache_id            BIGSERIAL PRIMARY KEY,
    normalized_query    TEXT        NOT NULL,
    query_hash          TEXT        NOT NULL,
    filter_hash         TEXT        NOT NULL,
    sort_key            TEXT        NOT NULL DEFAULT '',
    page_number         INT         NOT NULL DEFAULT 1,
    page_limit          INT         NOT NULL DEFAULT 10,
    ordered_product_ids TEXT[]      NOT NULL,
    result_count        INT         NOT NULL,
    response_meta       JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ NOT NULL,
    last_hit_at         TIMESTAMPTZ,
    hit_count           INT         NOT NULL DEFAULT 0,
    status              TEXT        NOT NULL DEFAULT 'ACTIVE'
);

-- Unique constraint: one entry per exact cache identity.
-- NOT NULL columns ensure uniqueness behaves deterministically (no NULL != NULL edge case).
CREATE UNIQUE INDEX IF NOT EXISTS query_cache_exact_key_idx
    ON query_cache (query_hash, filter_hash, sort_key, page_number, page_limit);

-- Index for expiry-based cleanup (DELETE WHERE expires_at <= now()).
CREATE INDEX IF NOT EXISTS query_cache_expires_at_idx
    ON query_cache (expires_at);

-- Optional: supports future LRU-style eviction analysis.
CREATE INDEX IF NOT EXISTS query_cache_last_hit_at_idx
    ON query_cache (last_hit_at);

-- Optional: GIN index on ordered_product_ids for future product-level invalidation
-- (e.g. invalidate all cache entries containing a specific product_id on price change).
CREATE INDEX IF NOT EXISTS query_cache_product_ids_gin_idx
    ON query_cache USING GIN (ordered_product_ids);
