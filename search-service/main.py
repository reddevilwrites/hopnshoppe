"""
search-service — Hybrid Semantic Search with Two-Layer Exact Cache
===================================================================

GET /search?q=...&limit=...

Returns denormalized product documents directly from the search_index table.
No downstream catalog-service call is made per result.

Cache Flow
----------
  L1 (in-process, TTL=2 min)
    → L2 (Postgres query_cache, TTL=10 min)
        → hybrid search on search_index
            → cache write (L2 + L1)
            → hydrated response

On any cache hit, current denormalized_doc rows are bulk-fetched from
search_index in one query — cached product IDs are the safe reuse unit.

Ranking (on cache miss only)
-----------------------------
  70% vector cosine similarity  (all-MiniLM-L6-v2, 384-dim)
  30% PostgreSQL ts_rank_cd     (full-text, GIN-indexed tsvector)
"""

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

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

# Cache TTL constants
L1_TTL_SECONDS = 120    # 2 minutes — hot in-process cache
L2_TTL_SECONDS = 600    # 10 minutes — persistent Postgres cache
L1_MAX_ENTRIES = 500    # evict oldest 10 % when this ceiling is reached

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

app = FastAPI(title="search-service", version="2.0.0")

# ---------------------------------------------------------------------------
# Query normalisation
# ---------------------------------------------------------------------------
_MULTI_SPACE = re.compile(r"\s+")


def normalize_query(q: str) -> str:
    """
    Normalise a raw search query for consistent cache keying.

    Rules (conservative — minimal lossy transforms):
      - strip leading/trailing whitespace
      - lowercase
      - collapse internal whitespace runs to a single space

    Examples:
      " Cheap   Waterproof Boots " → "cheap waterproof boots"
      "Running SHOES"              → "running shoes"
    """
    return _MULTI_SPACE.sub(" ", q.strip().lower())


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------
def _build_query_hash(
    normalized_query: str,
    filter_hash: str,
    sort_key: str,
    page_number: int,
    page_limit: int,
) -> str:
    """SHA-256 of the canonical cache identity string."""
    raw = f"{normalized_query}|{filter_hash}|{sort_key}|{page_number}|{page_limit}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# L1 — in-process TTL cache
# ---------------------------------------------------------------------------
@dataclass
class _L1Entry:
    ordered_product_ids: list
    result_count: int
    response_meta: dict
    expires_at: float   # monotonic time


_l1_cache: dict = {}

# Observable counters
_metrics = {
    "l1_hits":  0,
    "l2_hits":  0,
    "misses":   0,
    "writes":   0,
}


def _l1_get(query_hash: str) -> Optional[_L1Entry]:
    entry = _l1_cache.get(query_hash)
    if entry is None:
        return None
    if time.monotonic() > entry.expires_at:
        _l1_cache.pop(query_hash, None)
        return None
    return entry


def _l1_put(
    query_hash: str,
    ordered_product_ids: list,
    result_count: int,
    response_meta: dict,
) -> None:
    # Evict ~10 % of oldest-keyed entries when at capacity (insertion-order dict).
    if len(_l1_cache) >= L1_MAX_ENTRIES:
        evict_n = max(1, L1_MAX_ENTRIES // 10)
        for k in list(_l1_cache.keys())[:evict_n]:
            _l1_cache.pop(k, None)
    _l1_cache[query_hash] = _L1Entry(
        ordered_product_ids=ordered_product_ids,
        result_count=result_count,
        response_meta=response_meta,
        expires_at=time.monotonic() + L1_TTL_SECONDS,
    )


# ---------------------------------------------------------------------------
# L2 — Postgres exact cache
# ---------------------------------------------------------------------------
def _l2_get(
    query_hash: str,
    filter_hash: str,
    sort_key: str,
    page_number: int,
    page_limit: int,
) -> Optional[tuple]:
    """
    Look up an active, non-expired cache entry.
    Updates hit_count and last_hit_at in a single UPDATE … RETURNING.
    Returns (ordered_product_ids, result_count, response_meta) or None.
    """
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE query_cache
                SET    hit_count   = hit_count + 1,
                       last_hit_at = now()
                WHERE  query_hash  = %s
                  AND  filter_hash = %s
                  AND  sort_key    = %s
                  AND  page_number = %s
                  AND  page_limit  = %s
                  AND  expires_at  > now()
                  AND  status      = 'ACTIVE'
                RETURNING ordered_product_ids, result_count, response_meta
                """,
                (query_hash, filter_hash, sort_key, page_number, page_limit),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return (
            list(row["ordered_product_ids"]),
            row["result_count"],
            row["response_meta"] or {},
        )
    except psycopg2.Error as exc:
        logger.warning("L2 cache lookup error (non-fatal): %s", exc)
        return None


def _l2_put(
    normalized_query: str,
    query_hash: str,
    filter_hash: str,
    sort_key: str,
    page_number: int,
    page_limit: int,
    ordered_product_ids: list,
    result_count: int,
    response_meta: dict,
) -> None:
    """Upsert a cache entry. Silently ignores DB errors (non-blocking path)."""
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=L2_TTL_SECONDS)
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO query_cache (
                    normalized_query, query_hash, filter_hash, sort_key,
                    page_number, page_limit,
                    ordered_product_ids, result_count, response_meta,
                    expires_at, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ACTIVE')
                ON CONFLICT (query_hash, filter_hash, sort_key, page_number, page_limit)
                DO UPDATE SET
                    ordered_product_ids = EXCLUDED.ordered_product_ids,
                    result_count        = EXCLUDED.result_count,
                    response_meta       = EXCLUDED.response_meta,
                    expires_at          = EXCLUDED.expires_at,
                    status              = 'ACTIVE',
                    hit_count           = 0,
                    last_hit_at         = NULL,
                    created_at          = now()
                """,
                (
                    normalized_query, query_hash, filter_hash, sort_key,
                    page_number, page_limit,
                    ordered_product_ids, result_count,
                    json.dumps(response_meta), expires_at,
                ),
            )
        _metrics["writes"] += 1
    except psycopg2.Error as exc:
        logger.warning("L2 cache write error (non-fatal): %s", exc)


def _l2_cleanup_expired() -> None:
    """
    Lazily delete expired rows — called opportunistically on each cache write
    so the table does not grow unboundedly without a dedicated scheduler.
    """
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "DELETE FROM query_cache WHERE expires_at <= now()"
            )
    except psycopg2.Error as exc:
        logger.debug("L2 cleanup error (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Hydration — bulk fetch current docs from search_index
# ---------------------------------------------------------------------------
def _hydrate(ordered_product_ids: list) -> list:
    """
    Fetch denormalized_doc for the given product IDs in a single query, then
    restore the original cached ranking order.  Products removed from the
    index since the cache entry was written are silently omitted.
    """
    if not ordered_product_ids:
        return []
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT product_id, denormalized_doc "
                "FROM search_index "
                "WHERE product_id = ANY(%s)",
                (ordered_product_ids,),
            )
            rows = cur.fetchall()
        doc_map = {row["product_id"]: row["denormalized_doc"] for row in rows}
        # Preserve cached ranking order; skip any IDs no longer in the index.
        return [doc_map[pid] for pid in ordered_product_ids if pid in doc_map]
    except psycopg2.Error as exc:
        logger.error("Hydration fetch error: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Hybrid search query (ranking logic unchanged from v1.0.0)
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
    si.product_id,
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
    t_start = time.monotonic()

    # ── Step 1: Normalise and build cache key ────────────────────────────────
    normalized  = normalize_query(q)
    filter_hash = ""
    sort_key    = ""
    page_number = 1
    page_limit  = limit
    query_hash  = _build_query_hash(normalized, filter_hash, sort_key, page_number, page_limit)

    logger.info(
        "Search request — q=%r normalized=%r limit=%d query_hash=%.8s…",
        q, normalized, limit, query_hash,
    )

    # ── Step 2: Empty query guard ────────────────────────────────────────────
    if not normalized:
        return {"query": q, "total": 0, "results": [], "cache_hit_source": "EMPTY"}

    # ── Step 3: L1 in-process cache ──────────────────────────────────────────
    l1_entry = _l1_get(query_hash)
    if l1_entry is not None:
        _metrics["l1_hits"] += 1
        docs = _hydrate(l1_entry.ordered_product_ids)
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "Cache L1 HIT — normalized=%r hash=%.8s… results=%d latency_ms=%d",
            normalized, query_hash, len(docs), elapsed_ms,
        )
        return {"query": q, "total": len(docs), "results": docs, "cache_hit_source": "L1"}

    # ── Step 4: L2 Postgres exact cache ──────────────────────────────────────
    l2_result = _l2_get(query_hash, filter_hash, sort_key, page_number, page_limit)
    if l2_result is not None:
        ordered_ids, _cached_count, response_meta = l2_result
        _metrics["l2_hits"] += 1
        docs = _hydrate(ordered_ids)
        _l1_put(query_hash, ordered_ids, len(docs), response_meta)
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "Cache L2 HIT — normalized=%r hash=%.8s… results=%d latency_ms=%d",
            normalized, query_hash, len(docs), elapsed_ms,
        )
        return {"query": q, "total": len(docs), "results": docs, "cache_hit_source": "L2"}

    # ── Step 5: Cache miss — run hybrid search ───────────────────────────────
    _metrics["misses"] += 1
    try:
        t_embed = time.monotonic()
        embedding = model.encode(normalized).tolist()
        vec_str   = _vec_str(embedding)
        embed_ms  = int((time.monotonic() - t_embed) * 1000)

        t_search = time.monotonic()
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(HYBRID_SQL, {
                "embedding": vec_str,
                "query":     normalized,
                "limit":     limit,
            })
            rows = cur.fetchall()
        search_ms = int((time.monotonic() - t_search) * 1000)

        ordered_ids  = [row["product_id"] for row in rows]
        docs         = [row["denormalized_doc"] for row in rows]
        result_count = len(docs)

        response_meta = {
            "cache_version": 1,
            "search_mode":   "hybrid",
            "embed_ms":      embed_ms,
            "search_ms":     search_ms,
        }

        # Persist to L2 (lazy cleanup first), then warm L1.
        _l2_cleanup_expired()
        _l2_put(
            normalized, query_hash, filter_hash, sort_key,
            page_number, page_limit,
            ordered_ids, result_count, response_meta,
        )
        _l1_put(query_hash, ordered_ids, result_count, response_meta)

        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "Cache MISS — normalized=%r hash=%.8s… results=%d "
            "embed_ms=%d search_ms=%d total_ms=%d",
            normalized, query_hash, result_count, embed_ms, search_ms, elapsed_ms,
        )
        return {
            "query":            q,
            "total":            result_count,
            "results":          docs,
            "cache_hit_source": "MISS",
        }

    except psycopg2.Error as exc:
        logger.error("DB error during search: %s", exc)
        raise HTTPException(status_code=503, detail="Search temporarily unavailable")
    except Exception as exc:
        logger.error("Unexpected error during search: %s", exc)
        raise HTTPException(status_code=500, detail="Internal search error")


@app.get("/health")
def health():
    return {"status": "up"}


@app.get("/cache/stats")
def cache_stats():
    """Diagnostics: cache hit/miss counters and current L1 occupancy."""
    now = time.monotonic()
    l1_active = sum(1 for e in _l1_cache.values() if now <= e.expires_at)
    return {
        "l1_size_active":  l1_active,
        "l1_size_total":   len(_l1_cache),
        "l1_ttl_seconds":  L1_TTL_SECONDS,
        "l2_ttl_seconds":  L2_TTL_SECONDS,
        **_metrics,
    }
