-- Enable pgvector extension (provided by ankane/pgvector image).
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable pg_trgm extension for trigram-based text similarity (Phase 2 lexical-near cache).
CREATE EXTENSION IF NOT EXISTS pg_trgm;

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
--
-- Phase 2 additions (lexical-near cache):
--   lexical_signature  — normalised query text used for trigram matching
--                        (currently equal to normalized_query; reserved for
--                         future stemming/intent-stripping transforms)
--   query_tokens       — significant tokens after stopword removal, stored as
--                        a JSON array; used for token-overlap acceptance guards
--   cache_version      — schema version; 1 = Phase 1 exact, 2 = Phase 2+ rows
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
    status              TEXT        NOT NULL DEFAULT 'ACTIVE',
    -- Phase 2 columns ---------------------------------------------------------
    lexical_signature   TEXT,
    query_tokens        JSONB,
    cache_version       INT         NOT NULL DEFAULT 1
);

-- ── Migration guard: add Phase 2 columns to an existing Phase 1 table ───────
-- These statements are idempotent — they no-op when the column already exists.
-- Required when upgrading a running container that was initialised with the
-- Phase 1 schema (no lexical_signature / query_tokens / cache_version cols).
ALTER TABLE query_cache ADD COLUMN IF NOT EXISTS lexical_signature TEXT;
ALTER TABLE query_cache ADD COLUMN IF NOT EXISTS query_tokens       JSONB;
ALTER TABLE query_cache ADD COLUMN IF NOT EXISTS cache_version      INT NOT NULL DEFAULT 1;

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

-- ── Phase 2 trigram index ────────────────────────────────────────────────────
-- GIN trigram index on normalized_query for fast similarity-candidate retrieval.
-- Enables the `%` operator (pg_trgm) to use an index rather than a seq-scan.
-- GIN chosen over GiST: faster reads, acceptable write overhead for a cache table
-- where writes are far less frequent than reads.
CREATE INDEX IF NOT EXISTS query_cache_normalized_query_trgm_idx
    ON query_cache USING GIN (normalized_query gin_trgm_ops);
