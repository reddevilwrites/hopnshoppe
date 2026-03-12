"""
search-service — Hybrid Semantic Search
=========================================
GET /search?q=...&limit=...

Returns denormalized product documents directly from the search_index table.
No downstream catalog-service call is made per result.

Ranking
-------
  70% vector cosine similarity  (all-MiniLM-L6-v2, 384-dim)
  30% PostgreSQL ts_rank_cd     (full-text, GIN-indexed tsvector)

Strategy
--------
  1. Embed the query string.
  2. Retrieve the top-100 nearest neighbours by cosine distance (HNSW index).
  3. LEFT JOIN full-text candidates found via the GIN index.
  4. Compute weighted score, sort descending, return top N.
"""

import logging
import os
import time

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("search-service")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SEARCH_DB_HOST     = os.environ.get("SEARCH_DB_HOST", "search-db")
SEARCH_DB_PORT     = int(os.environ.get("SEARCH_DB_PORT", "5432"))
SEARCH_DB_NAME     = os.environ.get("SEARCH_DB_NAME", "search_db")
SEARCH_DB_USER     = os.environ.get("SEARCH_DB_USER", "postgres")
SEARCH_DB_PASSWORD = os.environ["SEARCH_DB_PASSWORD"]

EMBED_MODEL = "all-MiniLM-L6-v2"

# ---------------------------------------------------------------------------
# Startup — load model and connect to search-db (with retry)
# ---------------------------------------------------------------------------
logger.info("Loading embedding model '%s' …", EMBED_MODEL)
model = SentenceTransformer(EMBED_MODEL)


def _connect_db() -> psycopg2.extensions.connection:
    dsn = (
        f"host={SEARCH_DB_HOST} port={SEARCH_DB_PORT} "
        f"dbname={SEARCH_DB_NAME} user={SEARCH_DB_USER} "
        f"password={SEARCH_DB_PASSWORD}"
    )
    for attempt in range(1, 11):
        try:
            conn = psycopg2.connect(dsn)
            conn.autocommit = True
            logger.info("Connected to search-db on attempt %d", attempt)
            return conn
        except psycopg2.OperationalError as exc:
            logger.warning("DB connect attempt %d/10 failed: %s", attempt, exc)
            time.sleep(min(2 ** (attempt - 1), 30))
    raise RuntimeError("Could not connect to search-db after 10 attempts")


db_conn = _connect_db()

app = FastAPI(title="search-service", version="1.0.0")

# ---------------------------------------------------------------------------
# Hybrid search query
#
# vector_cands  — top-100 rows ordered by cosine distance (uses HNSW index)
# text_cands    — rows that match the FTS query     (uses GIN index)
#
# A product is included if it appears in *either* set.  This ensures:
#   • pure semantic matches (no keyword overlap) still surface
#   • pure keyword matches (e.g. exact SKU or brand) still surface
#
# Weights: 70 % vector + 30 % full-text.  ts_rank_cd returns values in [0,1]
# for typical queries; cosine similarity (1 - distance) is also in [0,1].
# ---------------------------------------------------------------------------
HYBRID_SQL = """
WITH vector_cands AS (
    SELECT product_id,
           1 - (embedding <=> %(embedding)s::vector) AS vector_score
    FROM search_index
    ORDER BY embedding <=> %(embedding)s::vector
    LIMIT 100
),
text_cands AS (
    SELECT product_id,
           ts_rank_cd(
               to_tsvector('english', search_text),
               plainto_tsquery('english', %(query)s)
           ) AS text_score
    FROM search_index
    WHERE to_tsvector('english', search_text)
          @@ plainto_tsquery('english', %(query)s)
)
SELECT
    si.denormalized_doc,
    (COALESCE(vc.vector_score, 0) * 0.7
     + COALESCE(tc.text_score,  0) * 0.3) AS score
FROM search_index si
LEFT JOIN vector_cands vc ON si.product_id = vc.product_id
LEFT JOIN text_cands   tc ON si.product_id = tc.product_id
WHERE vc.product_id IS NOT NULL
   OR tc.product_id IS NOT NULL
ORDER BY score DESC
LIMIT %(limit)s
"""


def _vec_str(embedding: list) -> str:
    """Encode a Python float list as a pgvector literal string."""
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/search")
def search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(default=10, ge=1, le=50, description="Max results to return"),
):
    logger.info("Search request — q=%r limit=%d", q, limit)

    try:
        embedding = model.encode(q.strip()).tolist()
        vec_str   = _vec_str(embedding)

        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(HYBRID_SQL, {
                "embedding": vec_str,
                "query":     q.strip(),
                "limit":     limit,
            })
            rows = cur.fetchall()

        results = [row["denormalized_doc"] for row in rows]
        logger.info("Search q=%r → %d result(s)", q, len(results))
        return {"query": q, "total": len(results), "results": results}

    except psycopg2.Error as exc:
        logger.error("DB error during search: %s", exc)
        raise HTTPException(status_code=503, detail="Search temporarily unavailable")
    except Exception as exc:
        logger.error("Unexpected error during search: %s", exc)
        raise HTTPException(status_code=500, detail="Internal search error")


@app.get("/health")
def health():
    return {"status": "up"}
