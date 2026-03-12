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
