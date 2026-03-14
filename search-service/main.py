"""
search-service — Hybrid Search + L1/L2/Lexical/Semantic Cache + TTL Freshness
==============================================================================
Version: 5.0.0

GET  /search?q=...&limit=...
POST /internal/invalidate    — event-driven cache invalidation

Returns denormalized product documents directly from the search_index table.
No downstream catalog-service call is made per result.

Cache Flow
----------
  L1 (in-process, TTL=2 min, hard-expiry + freshness checked)
    → L2 (Postgres query_cache, soft TTL=10 min, hard TTL=60 min)
        → Lexical-near (Phase 2, pg_trgm trigram similarity)
            → Semantic cache (Phase 3, pgvector cosine similarity)
                → Hybrid product search (70% vector + 30% FTS)
                    → cache write (ACTIVE, soft + hard expiry)
                    → hydrated response

On any cache hit, current denormalized_doc rows are bulk-fetched from
search_index in one query — cached product IDs are the safe reuse unit.

Freshness Model (Phase 4)
--------------------------
  ACTIVE       : now < soft_expires_at
                 — served normally
  SOFT_EXPIRED : soft_expires_at <= now < hard_expires_at,
                 OR event-driven invalidation (minor update: price, inventory, promo)
                 — served; background refresh triggered asynchronously after response
  HARD_EXPIRED : now >= hard_expires_at,
                 OR event-driven invalidation (FULL_UPDATE with core field changes)
                 — never served; falls through to recomputed search

TTL windows:
  soft TTL  = 10 minutes  (L2_SOFT_TTL_SECONDS)
  hard TTL  = 60 minutes  (L2_HARD_TTL_SECONDS)
  L1 TTL    =  2 minutes  (L1_TTL_SECONDS)

Event-driven invalidation by event_type:
  PRICE_UPDATE       → SOFT_EXPIRED
  INVENTORY_UPDATE   → SOFT_EXPIRED
  PROMOTION_UPDATE   → SOFT_EXPIRED
  FULL_UPDATE        → SOFT_EXPIRED by default;
                       HARD_EXPIRED if changed_fields contains core search fields

PostgreSQL NOTIFY (Phase 4):
  On invalidation, pg_notify('search_cache_invalidation', payload_json) is emitted.
  A daemon thread LISTENs and evicts matching L1 entries without Redis.

Lexical-Near Acceptance (Phase 2)
-----------------------------------
  1. pg_trgm similarity >= 0.76
  2. Incoming query has >= 2 significant tokens
  3. At least 2 significant tokens in common
  4. filter_hash, sort_key, page_number, page_limit match exactly
  5. Candidate hard_expires_at > now() and freshness_status != 'HARD_EXPIRED'

Semantic Cache Acceptance (Phase 3)
--------------------------------------
  strong accept  : similarity >= 0.88 — no extra token guardrails
  borderline     : 0.84 <= similarity < 0.88 — price-intent + token guardrails
  hard reject    : similarity < 0.84
"""

import hashlib
import json
import logging
import os
import re
import select
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import psycopg2
import psycopg2.extras
from psycopg2 import pool as psycopg2_pool
from contextlib import contextmanager, asynccontextmanager
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from pydantic import BaseModel
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

# ── Cache TTL constants ─────────────────────────────────────────────────────
L1_TTL_SECONDS      = 120     # 2 min — hot in-process cache (must be < soft TTL)
L1_MAX_ENTRIES      = 500     # evict oldest 10% when ceiling is reached
L2_SOFT_TTL_SECONDS = 600     # 10 min — ACTIVE window; SOFT_EXPIRED after this
L2_HARD_TTL_SECONDS = 3600    # 60 min — hard barrier; HARD_EXPIRED rows never served

# ── Lexical-near constants (Phase 2) ────────────────────────────────────────
LEXICAL_NEAR_SIMILARITY_THRESHOLD = 0.76
LEXICAL_NEAR_MAX_CANDIDATES       = 5
LEXICAL_NEAR_MIN_SHARED_TOKENS    = 2

# ── Semantic cache constants (Phase 3) ──────────────────────────────────────
SEMANTIC_STRONG_ACCEPT  = 0.88
SEMANTIC_BORDERLINE_LOW = 0.84
SEMANTIC_MAX_CANDIDATES = 5

# ── Phase 4: core search fields that trigger HARD_EXPIRED on FULL_UPDATE ────
_CORE_SEARCH_FIELDS = frozenset({"title", "search_text", "brand", "category"})

# ---------------------------------------------------------------------------
# DB connection string (module-level so listener thread can reuse it)
# ---------------------------------------------------------------------------
_DB_DSN = (
    f"host={SEARCH_DB_HOST} port={SEARCH_DB_PORT} "
    f"dbname={SEARCH_DB_NAME} user={SEARCH_DB_USER} "
    f"password={SEARCH_DB_PASSWORD}"
)

# ---------------------------------------------------------------------------
# Startup — load embedding model and connect to search-db (with retry)
# ---------------------------------------------------------------------------
logger.info("Loading embedding model '%s' …", EMBED_MODEL)
model = SentenceTransformer(EMBED_MODEL)


_db_pool: psycopg2_pool.ThreadedConnectionPool | None = None

def _init_pool() -> psycopg2_pool.ThreadedConnectionPool:
    """
    Create the connection pool with retry logic matching the old _connect_db.
    minconn=2 keeps two connections warm.
    maxconn=10 safely fits uvicorn's default worker count plus background tasks.
    autocommit is set per-connection at checkout time in get_db_conn().
    """
    for attempt in range(1, 11):
        try:
            p = psycopg2_pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=10,
                dsn=_DB_DSN,
            )
            logger.info("Connection pool created on attempt %d (min=2, max=10)", attempt)
            return p
        except psycopg2.OperationalError as exc:
            logger.warning("Pool init attempt %d/10 failed: %s", attempt, exc)
            time.sleep(min(2 ** (attempt - 1), 30))
    raise RuntimeError("Could not initialise connection pool after 10 attempts")


@contextmanager
def get_db_conn():
    """
    Checkout one connection from the pool, yield it, then return it.

    Design decisions:
      - conn.autocommit = True mirrors the original single-connection behaviour.
        Every cursor already commits implicitly; no explicit conn.commit() calls
        exist in this file. Changing this would require auditing every call site.
      - rollback() in the except branch resets any aborted-transaction state
        before the connection goes back into the pool, preventing
        InFailedSqlTransaction errors on the next checkout.
      - PoolError → 503 so the caller gets a clean HTTP error, not a crash.
    """
    global _db_pool
    try:
        conn = _db_pool.getconn()
    except psycopg2_pool.PoolError:
        raise HTTPException(status_code=503, detail="Search temporarily unavailable — DB pool exhausted")
    conn.autocommit = True
    try:
        yield conn
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        _db_pool.putconn(conn)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialise pool then start LISTEN daemon
    global _db_pool
    _db_pool = _init_pool()
    _start_invalidation_listener()
    yield
    # Shutdown: close all pooled connections cleanly
    if _db_pool:
        _db_pool.closeall()
        logger.info("Connection pool closed")

app = FastAPI(title="search-service", version="5.0.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Query normalisation
# ---------------------------------------------------------------------------
_MULTI_SPACE = re.compile(r"\s+")


def normalize_query(q: str) -> str:
    """Strip, lowercase, collapse whitespace."""
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
    raw = f"{normalized_query}|{filter_hash}|{sort_key}|{page_number}|{page_limit}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Tokeniser (Phase 2)
# ---------------------------------------------------------------------------
_STOPWORDS: frozenset = frozenset({
    "a", "an", "the", "and", "or", "of", "in", "to", "for",
    "with", "on", "at", "by", "is", "it", "its", "as", "be",
    "are", "was", "were", "that", "this", "from", "into", "up", "my", "me", "i", "do", "not", "no",
})
_TOKEN_SPLIT = re.compile(r"[\s\-_/.,;:!?&'\"()\[\]{}]+")

# Semantic intent-conflict term sets (Phase 3)
_BUDGET_TERMS  = frozenset({"cheap", "budget", "affordable", "inexpensive", "discount", "bargain"})
_PREMIUM_TERMS = frozenset({"premium", "luxury", "expensive", "high-end", "designer", "deluxe", "exclusive"})


def _tokenize(text: str) -> list:
    return [
        t for t in _TOKEN_SPLIT.split(text.lower())
        if t and len(t) > 1 and t not in _STOPWORDS
    ]


def _has_price_intent_conflict(tokens_a: list, tokens_b: list) -> bool:
    set_a, set_b = set(tokens_a), set(tokens_b)
    a_budget  = bool(set_a & _BUDGET_TERMS)
    a_premium = bool(set_a & _PREMIUM_TERMS)
    b_budget  = bool(set_b & _BUDGET_TERMS)
    b_premium = bool(set_b & _PREMIUM_TERMS)
    return (a_budget and b_premium) or (a_premium and b_budget)


# ---------------------------------------------------------------------------
# Phase 4 — Freshness helpers
# ---------------------------------------------------------------------------
def _effective_freshness(stored_status: str, soft_expires_at: Optional[datetime]) -> str:
    """
    Compute the runtime freshness state from the stored status and soft_expires_at.

    Priority:
      1. If stored_status is already HARD_EXPIRED (event-driven) → HARD_EXPIRED
      2. If stored_status is SOFT_EXPIRED (event-driven) → SOFT_EXPIRED
      3. If soft_expires_at has passed → SOFT_EXPIRED
      4. Otherwise → ACTIVE
    """
    if stored_status == "HARD_EXPIRED":
        return "HARD_EXPIRED"
    if stored_status == "SOFT_EXPIRED":
        return "SOFT_EXPIRED"
    if soft_expires_at is not None:
        now_utc = datetime.now(timezone.utc)
        # Ensure timezone-aware comparison
        sa = soft_expires_at if soft_expires_at.tzinfo else soft_expires_at.replace(tzinfo=timezone.utc)
        if now_utc >= sa:
            return "SOFT_EXPIRED"
    return "ACTIVE"


# ---------------------------------------------------------------------------
# L1 — in-process TTL cache (Phase 4: freshness-aware)
# ---------------------------------------------------------------------------
@dataclass
class _L1Entry:
    ordered_product_ids: list
    result_count: int
    response_meta: dict
    expires_at: float           # monotonic time — L1 TTL ceiling
    hard_expires_at: datetime   # wall-clock UTC — mirrors L2 hard_expires_at
    freshness_status: str       # ACTIVE or SOFT_EXPIRED snapshot from L2 at write time


_l1_cache: dict = {}

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
_metrics = {
    # Phase 1–3 counters
    "l1_hits":                   0,
    "l2_hits":                   0,
    "lexical_near_hits":         0,
    "lexical_near_rejects":      0,
    "semantic_hits":             0,
    "semantic_rejects":          0,
    "semantic_candidates_seen":  0,
    "embeddings_computed":       0,
    "misses":                    0,
    "writes":                    0,
    # Phase 4 counters
    "active_cache_hits":         0,
    "soft_expired_cache_hits":   0,
    "hard_expired_rejects":      0,
    "refresh_triggers":          0,
    "refresh_successes":         0,
    "refresh_failures":          0,
    "invalidation_events":       0,
    "invalidated_rows":          0,
    "l1_evictions_from_notify":  0,
}


def _l1_get(query_hash: str) -> Optional["_L1Entry"]:
    """
    Return an L1 entry if it is within L1 TTL, not hard-expired, and not HARD_EXPIRED.
    Returns None and evicts the entry if any freshness check fails.
    """
    entry = _l1_cache.get(query_hash)
    if entry is None:
        return None

    now_mono = time.monotonic()
    now_wall = datetime.now(timezone.utc)

    # L1 TTL check
    if now_mono > entry.expires_at:
        _l1_cache.pop(query_hash, None)
        return None

    # Hard-expiry check: don't serve an L1 entry whose L2 row has hard-expired
    hard = entry.hard_expires_at
    hard_utc = hard if hard.tzinfo else hard.replace(tzinfo=timezone.utc)
    if now_wall >= hard_utc:
        _l1_cache.pop(query_hash, None)
        return None

    # Event-driven HARD_EXPIRED: evict so the caller falls through to L2
    if entry.freshness_status == "HARD_EXPIRED":
        _l1_cache.pop(query_hash, None)
        return None

    return entry


def _l1_put(
    query_hash: str,
    ordered_product_ids: list,
    result_count: int,
    response_meta: dict,
    hard_expires_at: Optional[datetime] = None,
    freshness_status: str = "ACTIVE",
) -> None:
    if len(_l1_cache) >= L1_MAX_ENTRIES:
        evict_n = max(1, L1_MAX_ENTRIES // 10)
        for k in list(_l1_cache.keys())[:evict_n]:
            _l1_cache.pop(k, None)
    # Default hard_expires_at: L2_HARD_TTL from now (conservative)
    if hard_expires_at is None:
        hard_expires_at = datetime.now(timezone.utc) + timedelta(seconds=L2_HARD_TTL_SECONDS)
    _l1_cache[query_hash] = _L1Entry(
        ordered_product_ids=ordered_product_ids,
        result_count=result_count,
        response_meta=response_meta,
        expires_at=time.monotonic() + L1_TTL_SECONDS,
        hard_expires_at=hard_expires_at,
        freshness_status=freshness_status,
    )


def _l1_evict_by_product_id(product_id: str) -> int:
    """
    Scan L1 and evict all entries whose ordered_product_ids include product_id.
    O(n) scan over ≤500 entries — acceptable for this cache size.
    Returns the number of entries evicted.
    """
    keys_to_remove = [
        k for k, e in _l1_cache.items()
        if product_id in e.ordered_product_ids
    ]
    for k in keys_to_remove:
        _l1_cache.pop(k, None)
    return len(keys_to_remove)


# ---------------------------------------------------------------------------
# L2 — Postgres exact cache (Phase 4: freshness-aware)
# ---------------------------------------------------------------------------
@dataclass
class _L2Result:
    ordered_product_ids: list
    result_count: int
    response_meta: dict
    freshness_status: str       # effective freshness (ACTIVE or SOFT_EXPIRED)
    hard_expires_at: datetime   # for storing in L1


def _l2_get(
    query_hash: str,
    filter_hash: str,
    sort_key: str,
    page_number: int,
    page_limit: int,
) -> Optional[_L2Result]:
    """
    Look up a cache entry that is within its hard TTL and not HARD_EXPIRED.
    Updates hit_count / last_hit_at in the same UPDATE … RETURNING.
    Returns an _L2Result with effective freshness (ACTIVE or SOFT_EXPIRED), or None.
    """
    try:
        with get_db_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE query_cache
                    SET    hit_count   = hit_count + 1,
                           last_hit_at = now()
                    WHERE  query_hash        = %s
                      AND  filter_hash       = %s
                      AND  sort_key          = %s
                      AND  page_number       = %s
                      AND  page_limit        = %s
                      AND  hard_expires_at   > now()
                      AND  freshness_status != 'HARD_EXPIRED'
                    RETURNING ordered_product_ids, result_count, response_meta,
                              freshness_status, soft_expires_at, hard_expires_at
                    """,
                    (query_hash, filter_hash, sort_key, page_number, page_limit),
                )
                row = cur.fetchone()
        if row is None:
            return None
        eff = _effective_freshness(row["freshness_status"], row["soft_expires_at"])
        hard_dt = row["hard_expires_at"]
        if hard_dt and hard_dt.tzinfo is None:
            hard_dt = hard_dt.replace(tzinfo=timezone.utc)
        return _L2Result(
            ordered_product_ids=list(row["ordered_product_ids"]),
            result_count=row["result_count"],
            response_meta=row["response_meta"] or {},
            freshness_status=eff,
            hard_expires_at=hard_dt or datetime.now(timezone.utc) + timedelta(seconds=L2_HARD_TTL_SECONDS),
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
    query_tokens: Optional[list] = None,
    cache_version: int = 2,
    query_embedding_str: Optional[str] = None,
    semantic_source_query: Optional[str] = None,
    semantic_similarity: Optional[float] = None,
    semantic_meta: Optional[dict] = None,
) -> None:
    """
    Upsert a cache entry with Phase 4 freshness fields.
    Always writes freshness_status = 'ACTIVE' with new soft + hard expiry windows.
    Silently ignores DB errors (non-blocking write path).
    """
    now_utc       = datetime.now(timezone.utc)
    soft_expires  = now_utc + timedelta(seconds=L2_SOFT_TTL_SECONDS)
    hard_expires  = now_utc + timedelta(seconds=L2_HARD_TTL_SECONDS)
    # Keep expires_at = hard_expires for backward compatibility with old cleanup code.
    expires_at    = hard_expires
    tokens_json   = json.dumps(query_tokens) if query_tokens is not None else None
    sem_meta_json = json.dumps(semantic_meta) if semantic_meta is not None else None

    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO query_cache (
                        normalized_query, query_hash, filter_hash, sort_key,
                        page_number, page_limit,
                        ordered_product_ids, result_count, response_meta,
                        expires_at, status,
                        lexical_signature, query_tokens, cache_version,
                        query_embedding, semantic_source_query, semantic_similarity, semantic_meta,
                        soft_expires_at, hard_expires_at, freshness_status,
                        last_refresh_at, affected_product_ids,
                        invalidation_reason, invalidated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, 'ACTIVE',
                        %s, %s, %s,
                        %s::vector, %s, %s, %s,
                        %s, %s, 'ACTIVE',
                        now(), %s,
                        NULL, NULL
                    )
                    ON CONFLICT (query_hash, filter_hash, sort_key, page_number, page_limit)
                    DO UPDATE SET
                        ordered_product_ids   = EXCLUDED.ordered_product_ids,
                        result_count          = EXCLUDED.result_count,
                        response_meta         = EXCLUDED.response_meta,
                        expires_at            = EXCLUDED.expires_at,
                        status                = 'ACTIVE',
                        hit_count             = 0,
                        last_hit_at           = NULL,
                        created_at            = now(),
                        lexical_signature     = EXCLUDED.lexical_signature,
                        query_tokens          = EXCLUDED.query_tokens,
                        cache_version         = EXCLUDED.cache_version,
                        query_embedding       = COALESCE(EXCLUDED.query_embedding,       query_cache.query_embedding),
                        semantic_source_query = COALESCE(EXCLUDED.semantic_source_query, query_cache.semantic_source_query),
                        semantic_similarity   = COALESCE(EXCLUDED.semantic_similarity,   query_cache.semantic_similarity),
                        semantic_meta         = COALESCE(EXCLUDED.semantic_meta,         query_cache.semantic_meta),
                        soft_expires_at       = EXCLUDED.soft_expires_at,
                        hard_expires_at       = EXCLUDED.hard_expires_at,
                        freshness_status      = 'ACTIVE',
                        last_refresh_at       = now(),
                        affected_product_ids  = EXCLUDED.affected_product_ids,
                        invalidation_reason   = NULL,
                        invalidated_at        = NULL
                    """,
                    (
                        normalized_query, query_hash, filter_hash, sort_key,
                        page_number, page_limit,
                        ordered_product_ids, result_count,
                        json.dumps(response_meta), expires_at,
                        normalized_query,       # lexical_signature
                        tokens_json,
                        cache_version,
                        query_embedding_str,    # None → NULL::vector (valid)
                        semantic_source_query,
                        semantic_similarity,
                        sem_meta_json,
                        soft_expires,
                        hard_expires,
                        ordered_product_ids,    # affected_product_ids = ordered_product_ids
                    ),
                )
        _metrics["writes"] += 1
    except psycopg2.Error as exc:
        logger.warning("L2 cache write error (non-fatal): %s", exc)


def _l2_cleanup_expired() -> None:
    """
    Lazily delete rows that have been hard-expired for more than 24 hours.
    Called opportunistically on each cache write — no dedicated scheduler needed.
    """
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM query_cache WHERE hard_expires_at < now() - interval '24 hours'"
                )
    except psycopg2.Error as exc:
        logger.debug("L2 cleanup error (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Phase 4 — Invalidation
# ---------------------------------------------------------------------------
def _invalidation_severity(event_type: str, changed_fields: Optional[list]) -> str:
    """
    Map an event_type to a freshness_status target.

    PRICE_UPDATE / INVENTORY_UPDATE / PROMOTION_UPDATE → SOFT_EXPIRED
    FULL_UPDATE → SOFT_EXPIRED by default;
                  HARD_EXPIRED if changed_fields includes a core search field
                  (title, search_text, brand, category)
    """
    if event_type == "FULL_UPDATE" and changed_fields:
        if _CORE_SEARCH_FIELDS & set(changed_fields):
            return "HARD_EXPIRED"
    return "SOFT_EXPIRED"


def _notify_invalidation(product_id: str, event_type: str, rows_updated: int) -> None:
    """Emit a PostgreSQL NOTIFY on 'search_cache_invalidation' for L1 coherence."""
    payload = json.dumps({
        "product_id": product_id,
        "event_type": event_type,
        "rows":       rows_updated,
    })
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_notify('search_cache_invalidation', %s)", (payload,))
    except psycopg2.Error as exc:
        logger.debug("NOTIFY failed (non-fatal): %s", exc)


def _invalidate_product(
    product_id: str,
    event_type: str,
    changed_fields: Optional[list] = None,
) -> int:
    """
    Mark all active query_cache rows containing product_id as SOFT_EXPIRED or HARD_EXPIRED.

    Uses a GIN-indexed ANY() lookup on affected_product_ids (falls back to
    ordered_product_ids for rows written before Phase 4).

    Returns the number of rows updated.
    """
    new_status = _invalidation_severity(event_type, changed_fields)
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE query_cache
                    SET    freshness_status    = %s,
                           invalidation_reason = %s,
                           invalidated_at      = now()
                    WHERE  freshness_status = 'ACTIVE'
                      AND  hard_expires_at  > now()
                      AND  (
                               %s = ANY(COALESCE(affected_product_ids, ordered_product_ids))
                           )
                    """,
                    (new_status, event_type, product_id),
                )
                updated = cur.rowcount

        # Evict matching L1 entries immediately (no wait for NOTIFY round-trip)
        l1_evicted = _l1_evict_by_product_id(product_id)

        _metrics["invalidation_events"] += 1
        _metrics["invalidated_rows"]    += updated
        _metrics["l1_evictions_from_notify"] += l1_evicted

        logger.info(
            "Invalidation — product_id=%r event=%s target_status=%s "
            "rows_updated=%d l1_evicted=%d",
            product_id, event_type, new_status, updated, l1_evicted,
        )

        # Notify sibling instances (if running multiple replicas)
        _notify_invalidation(product_id, event_type, updated)

        return updated
    except psycopg2.Error as exc:
        logger.warning("Invalidation DB error: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# Phase 4 — Background refresh (called via FastAPI BackgroundTasks)
# ---------------------------------------------------------------------------
def _refresh_cache_entry(
    normalized: str,
    query_hash: str,
    filter_hash: str,
    sort_key: str,
    page_number: int,
    page_limit: int,
    incoming_tokens: list,
) -> None:
    """
    Run a fresh hybrid search and overwrite a soft-expired cache entry.
    Called asynchronously after response is sent — uses its own DB connection
    to avoid contention with the main request connection.
    """
    _metrics["refresh_triggers"] += 1
    refresh_conn = None
    try:
        refresh_conn = psycopg2.connect(_DB_DSN)
        refresh_conn.autocommit = True

        embedding = model.encode(normalized).tolist()
        vec_str   = _vec_str(embedding)

        with refresh_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(HYBRID_SQL, {
                "embedding": vec_str,
                "query":     normalized,
                "limit":     page_limit,
            })
            rows = cur.fetchall()

        ordered_ids  = [row["product_id"] for row in rows]
        result_count = len(ordered_ids)

        response_meta = {
            "cache_version": 5,
            "search_mode":   "hybrid",
            "refreshed":     True,
        }

        # Upsert fresh entry (resets freshness_status = 'ACTIVE', new soft/hard TTLs)
        now_utc      = datetime.now(timezone.utc)
        soft_expires = now_utc + timedelta(seconds=L2_SOFT_TTL_SECONDS)
        hard_expires = now_utc + timedelta(seconds=L2_HARD_TTL_SECONDS)
        tokens_json  = json.dumps(incoming_tokens)

        with refresh_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO query_cache (
                    normalized_query, query_hash, filter_hash, sort_key,
                    page_number, page_limit,
                    ordered_product_ids, result_count, response_meta,
                    expires_at, status,
                    lexical_signature, query_tokens, cache_version,
                    query_embedding,
                    soft_expires_at, hard_expires_at, freshness_status,
                    last_refresh_at, affected_product_ids,
                    invalidation_reason, invalidated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, 'ACTIVE',
                    %s, %s, 5,
                    %s::vector,
                    %s, %s, 'ACTIVE',
                    now(), %s,
                    NULL, NULL
                )
                ON CONFLICT (query_hash, filter_hash, sort_key, page_number, page_limit)
                DO UPDATE SET
                    ordered_product_ids  = EXCLUDED.ordered_product_ids,
                    result_count         = EXCLUDED.result_count,
                    response_meta        = EXCLUDED.response_meta,
                    expires_at           = EXCLUDED.expires_at,
                    status               = 'ACTIVE',
                    hit_count            = 0,
                    last_hit_at          = NULL,
                    created_at           = now(),
                    query_tokens         = EXCLUDED.query_tokens,
                    cache_version        = EXCLUDED.cache_version,
                    query_embedding      = COALESCE(EXCLUDED.query_embedding, query_cache.query_embedding),
                    soft_expires_at      = EXCLUDED.soft_expires_at,
                    hard_expires_at      = EXCLUDED.hard_expires_at,
                    freshness_status     = 'ACTIVE',
                    last_refresh_at      = now(),
                    affected_product_ids = EXCLUDED.affected_product_ids,
                    invalidation_reason  = NULL,
                    invalidated_at       = NULL
                """,
                (
                    normalized, query_hash, filter_hash, sort_key,
                    page_number, page_limit,
                    ordered_ids, result_count, json.dumps(response_meta),
                    hard_expires,
                    normalized, tokens_json,
                    vec_str,
                    soft_expires, hard_expires,
                    ordered_ids,
                ),
            )

        # Warm L1 with the fresh result
        _l1_put(
            query_hash, ordered_ids, result_count, response_meta,
            hard_expires_at=hard_expires,
            freshness_status="ACTIVE",
        )

        _metrics["refresh_successes"] += 1
        logger.info(
            "Background refresh OK — normalized=%r results=%d",
            normalized, result_count,
        )
    except Exception as exc:
        _metrics["refresh_failures"] += 1
        logger.warning("Background refresh failed — normalized=%r error=%s", normalized, exc)
    finally:
        if refresh_conn:
            try:
                refresh_conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Phase 4 — LISTEN/NOTIFY daemon (L1 coherence across invalidation events)
# ---------------------------------------------------------------------------
def _handle_invalidation_notify(payload: str) -> None:
    """Process a NOTIFY payload: evict matching L1 entries."""
    try:
        data       = json.loads(payload)
        product_id = data.get("product_id")
        if product_id:
            evicted = _l1_evict_by_product_id(product_id)
            _metrics["l1_evictions_from_notify"] += evicted
            if evicted:
                logger.info(
                    "NOTIFY L1 eviction — product_id=%r evicted=%d",
                    product_id, evicted,
                )
    except (json.JSONDecodeError, Exception) as exc:
        logger.debug("Notify handler error: %s", exc)


def _invalidation_listener_loop() -> None:
    """
    Daemon thread: LISTENs on 'search_cache_invalidation' PostgreSQL channel.
    On NOTIFY, evicts matching L1 entries immediately.
    Reconnects automatically on any error.
    """
    while True:
        listen_conn = None
        try:
            listen_conn = psycopg2.connect(_DB_DSN)
            listen_conn.autocommit = True
            with listen_conn.cursor() as cur:
                cur.execute("LISTEN search_cache_invalidation")
            logger.info("LISTEN search_cache_invalidation: ready")
            while True:
                # Block up to 30 s waiting for notifications
                readable, _, _ = select.select([listen_conn], [], [], 30.0)
                if readable:
                    listen_conn.poll()
                    while listen_conn.notifies:
                        notify = listen_conn.notifies.pop(0)
                        _handle_invalidation_notify(notify.payload)
        except Exception as exc:
            logger.warning(
                "Invalidation listener error: %s — reconnecting in 5s", exc
            )
            time.sleep(5)
        finally:
            if listen_conn:
                try:
                    listen_conn.close()
                except Exception:
                    pass


def _start_invalidation_listener() -> None:
    t = threading.Thread(
        target=_invalidation_listener_loop,
        daemon=True,
        name="invalidation-listener",
    )
    t.start()
    logger.info("Invalidation listener thread started")


# LISTEN/NOTIFY daemon is started inside the lifespan() context manager above.


# ---------------------------------------------------------------------------
# Phase 2 — Lexical-near cache lookup (Phase 4: freshness-aware)
# ---------------------------------------------------------------------------
def _lexical_near_get(
    normalized_query: str,
    filter_hash: str,
    sort_key: str,
    page_number: int,
    page_limit: int,
) -> list:
    """
    Retrieve candidate cache entries whose normalized_query is trigram-similar
    to the incoming normalized_query.

    Filters:
      - hard_expires_at > now()           (hard barrier)
      - freshness_status != 'HARD_EXPIRED' (event-driven hard reject)

    Returns a list of dicts including freshness_status and soft_expires_at
    so the caller can compute effective freshness.
    """
    try:
        with get_db_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT normalized_query,
                           ordered_product_ids,
                           result_count,
                           response_meta,
                           query_tokens,
                           freshness_status,
                           soft_expires_at,
                           hard_expires_at,
                           similarity(normalized_query, %s) AS trgm_score
                    FROM query_cache
                    WHERE normalized_query  %% %s
                      AND filter_hash        = %s
                      AND sort_key           = %s
                      AND page_number        = %s
                      AND page_limit         = %s
                      AND hard_expires_at    > now()
                      AND freshness_status  != 'HARD_EXPIRED'
                    ORDER BY similarity(normalized_query, %s) DESC
                    LIMIT %s
                    """,
                    (
                        normalized_query,
                        normalized_query,
                        filter_hash,
                        sort_key,
                        page_number,
                        page_limit,
                        normalized_query,
                        LEXICAL_NEAR_MAX_CANDIDATES,
                    ),
                )
                rows = cur.fetchall()
        return [dict(row) for row in rows]
    except psycopg2.Error as exc:
        logger.warning("Lexical-near candidate fetch error (non-fatal): %s", exc)
        return []


def _accept_lexical_near_candidate(
    incoming_tokens: list,
    candidate: dict,
) -> tuple:
    """
    Apply acceptance guardrails to a single lexical-near candidate.
    Returns (accepted: bool, stats: dict).
    """
    trgm_score           = float(candidate.get("trgm_score", 0.0))
    candidate_normalized = candidate["normalized_query"]

    raw_tokens = candidate.get("query_tokens")
    if isinstance(raw_tokens, list):
        candidate_tokens = raw_tokens
    elif isinstance(raw_tokens, str):
        try:
            candidate_tokens = json.loads(raw_tokens)
        except (json.JSONDecodeError, TypeError):
            candidate_tokens = _tokenize(candidate_normalized)
    else:
        candidate_tokens = _tokenize(candidate_normalized)

    stats = {
        "trgm_score":           round(trgm_score, 4),
        "candidate_normalized": candidate_normalized,
    }

    if trgm_score < LEXICAL_NEAR_SIMILARITY_THRESHOLD:
        stats["reject_reason"] = "low_trgm_similarity"
        return False, stats

    if len(incoming_tokens) <= 1:
        stats["reject_reason"] = "single_token_query"
        return False, stats

    shared       = set(incoming_tokens) & set(candidate_tokens)
    shared_count = len(shared)
    stats["shared_tokens"]       = sorted(shared)
    stats["shared_count"]        = shared_count
    stats["token_overlap_ratio"] = round(shared_count / max(len(incoming_tokens), 1), 3)

    if shared_count < LEXICAL_NEAR_MIN_SHARED_TOKENS:
        stats["reject_reason"] = "insufficient_token_overlap"
        return False, stats

    return True, stats


# ---------------------------------------------------------------------------
# Phase 3 — Semantic cache lookup (Phase 4: freshness-aware)
# ---------------------------------------------------------------------------
def _semantic_get(
    embedding_str: str,
    filter_hash: str,
    sort_key: str,
    page_number: int,
    page_limit: int,
) -> list:
    """
    Exact cosine scan over query_cache.query_embedding.

    Filters:
      - hard_expires_at > now()
      - freshness_status != 'HARD_EXPIRED'
      - query_embedding IS NOT NULL
      - semantic_cache_enabled = TRUE

    Returns rows with freshness_status and soft_expires_at for Phase 4 checks.
    """
    try:
        with get_db_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        normalized_query,
                        ordered_product_ids,
                        result_count,
                        query_tokens,
                        freshness_status,
                        soft_expires_at,
                        hard_expires_at,
                        query_embedding <=> %s::vector             AS cosine_distance,
                        1 - (query_embedding <=> %s::vector)       AS semantic_similarity
                    FROM query_cache
                    WHERE query_embedding        IS NOT NULL
                      AND hard_expires_at        > now()
                      AND freshness_status      != 'HARD_EXPIRED'
                      AND semantic_cache_enabled = TRUE
                      AND filter_hash            = %s
                      AND COALESCE(sort_key, '') = COALESCE(%s, '')
                      AND page_number            = %s
                      AND page_limit             = %s
                    ORDER BY query_embedding <=> %s::vector ASC
                    LIMIT %s
                    """,
                    (
                        embedding_str,
                        embedding_str,
                        filter_hash,
                        sort_key,
                        page_number,
                        page_limit,
                        embedding_str,
                        SEMANTIC_MAX_CANDIDATES,
                    ),
                )
                rows = cur.fetchall()
        return [dict(row) for row in rows]
    except psycopg2.Error as exc:
        logger.warning("Semantic candidate fetch error (non-fatal): %s", exc)
        return []


def _accept_semantic_candidate(
    incoming_tokens: list,
    candidate: dict,
) -> tuple:
    """
    Validate a single semantic cache candidate.
    Returns (accepted: bool, stats: dict).
    """
    similarity           = float(candidate.get("semantic_similarity", 0.0))
    candidate_normalized = candidate["normalized_query"]

    stats = {
        "similarity":           round(similarity, 4),
        "candidate_normalized": candidate_normalized,
    }

    if similarity < SEMANTIC_BORDERLINE_LOW:
        stats["reject_reason"] = "low_similarity"
        return False, stats

    raw_tokens = candidate.get("query_tokens")
    if isinstance(raw_tokens, list):
        candidate_tokens = raw_tokens
    elif isinstance(raw_tokens, str):
        try:
            candidate_tokens = json.loads(raw_tokens)
        except (json.JSONDecodeError, TypeError):
            candidate_tokens = _tokenize(candidate_normalized)
    else:
        candidate_tokens = _tokenize(candidate_normalized)

    if _has_price_intent_conflict(incoming_tokens, candidate_tokens):
        stats["reject_reason"] = "price_intent_conflict"
        return False, stats

    if similarity >= SEMANTIC_STRONG_ACCEPT:
        stats["band"] = "strong"
        return True, stats

    shared       = set(incoming_tokens) & set(candidate_tokens)
    shared_count = len(shared)
    stats["shared_tokens"] = sorted(shared)
    stats["shared_count"]  = shared_count

    if len(incoming_tokens) > 1 and shared_count < 2:
        stats["reject_reason"] = "borderline_insufficient_token_overlap"
        return False, stats

    stats["band"] = "borderline"
    return True, stats


# ---------------------------------------------------------------------------
# Hydration — bulk fetch current docs from search_index
# ---------------------------------------------------------------------------
def _hydrate(ordered_product_ids: list) -> list:
    """Fetch denormalized_doc for the given IDs in one query, preserving rank order."""
    if not ordered_product_ids:
        return []
    try:
        with get_db_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT product_id, denormalized_doc "
                    "FROM search_index "
                    "WHERE product_id = ANY(%s)",
                    (ordered_product_ids,),
                )
                rows = cur.fetchall()
        doc_map = {row["product_id"]: row["denormalized_doc"] for row in rows}
        return [doc_map[pid] for pid in ordered_product_ids if pid in doc_map]
    except psycopg2.Error as exc:
        logger.error("Hydration fetch error: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Hybrid search query (ranking logic unchanged from v1.0.0)
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
# Request models
# ---------------------------------------------------------------------------
class InvalidateRequest(BaseModel):
    product_id:     str
    event_type:     str                    # PRICE_UPDATE | INVENTORY_UPDATE | FULL_UPDATE | PROMOTION_UPDATE
    changed_fields: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/search")
def search(
    background_tasks: BackgroundTasks,
    q: str   = Query(..., min_length=1, description="Search query"),
    limit: int = Query(default=10, ge=1, le=50, description="Max results"),
):
    t_start = time.monotonic()

    # ── Step 1: Normalise and build cache key ────────────────────────────────
    normalized  = normalize_query(q)
    filter_hash = ""
    sort_key    = ""
    page_number = 1
    page_limit  = limit
    query_hash  = _build_query_hash(normalized, filter_hash, sort_key, page_number, page_limit)
    incoming_tokens = _tokenize(normalized)

    logger.info(
        "Search request — q=%r normalized=%r tokens=%s limit=%d hash=%.8s…",
        q, normalized, incoming_tokens, limit, query_hash,
    )

    # ── Step 2: Empty query guard ────────────────────────────────────────────
    if not normalized:
        return {"query": q, "total": 0, "results": [], "cache_hit_source": "EMPTY"}

    # ── Step 3: L1 in-process cache ──────────────────────────────────────────
    l1_entry = _l1_get(query_hash)
    if l1_entry is not None:
        _metrics["l1_hits"] += 1
        eff = l1_entry.freshness_status     # ACTIVE or SOFT_EXPIRED (HARD_EXPIRED evicted)
        if eff == "SOFT_EXPIRED":
            _metrics["soft_expired_cache_hits"] += 1
            background_tasks.add_task(
                _refresh_cache_entry,
                normalized, query_hash, filter_hash, sort_key,
                page_number, page_limit, incoming_tokens,
            )
        else:
            _metrics["active_cache_hits"] += 1

        docs       = _hydrate(l1_entry.ordered_product_ids)
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "Cache L1 HIT — normalized=%r hash=%.8s… freshness=%s results=%d latency_ms=%d",
            normalized, query_hash, eff, len(docs), elapsed_ms,
        )
        return {
            "query": q, "total": len(docs), "results": docs,
            "cache_hit_source": "L1", "freshness_status": eff,
        }

    # ── Step 4: L2 Postgres exact cache ──────────────────────────────────────
    l2_result = _l2_get(query_hash, filter_hash, sort_key, page_number, page_limit)
    if l2_result is not None:
        eff = l2_result.freshness_status    # ACTIVE or SOFT_EXPIRED
        if eff == "SOFT_EXPIRED":
            _metrics["soft_expired_cache_hits"] += 1
            background_tasks.add_task(
                _refresh_cache_entry,
                normalized, query_hash, filter_hash, sort_key,
                page_number, page_limit, incoming_tokens,
            )
        else:
            _metrics["active_cache_hits"] += 1
        _metrics["l2_hits"] += 1

        docs = _hydrate(l2_result.ordered_product_ids)
        _l1_put(
            query_hash, l2_result.ordered_product_ids, len(docs), l2_result.response_meta,
            hard_expires_at=l2_result.hard_expires_at,
            freshness_status=eff,
        )
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "Cache L2 HIT — normalized=%r hash=%.8s… freshness=%s results=%d latency_ms=%d",
            normalized, query_hash, eff, len(docs), elapsed_ms,
        )
        return {
            "query": q, "total": len(docs), "results": docs,
            "cache_hit_source": "L2", "freshness_status": eff,
        }

    # ── Step 5: Lexical-near cache lookup ────────────────────────────────────
    candidates = _lexical_near_get(
        normalized, filter_hash, sort_key, page_number, page_limit
    )
    logger.info(
        "Lexical-near candidates — normalized=%r count=%d",
        normalized, len(candidates),
    )

    for candidate in candidates:
        # Phase 4: compute effective freshness of this candidate before acceptance
        cand_eff = _effective_freshness(
            candidate.get("freshness_status", "ACTIVE"),
            candidate.get("soft_expires_at"),
        )
        # HARD_EXPIRED candidates are skipped regardless of similarity
        if cand_eff == "HARD_EXPIRED":
            _metrics["hard_expired_rejects"] += 1
            continue

        accepted, accept_stats = _accept_lexical_near_candidate(incoming_tokens, candidate)
        if not accepted:
            _metrics["lexical_near_rejects"] += 1
            logger.info(
                "Lexical-near REJECT — normalized=%r candidate=%r "
                "trgm_score=%.4f reason=%s",
                normalized,
                candidate["normalized_query"],
                accept_stats.get("trgm_score", 0.0),
                accept_stats.get("reject_reason", "unknown"),
            )
            continue

        _metrics["lexical_near_hits"] += 1
        if cand_eff == "SOFT_EXPIRED":
            _metrics["soft_expired_cache_hits"] += 1
        else:
            _metrics["active_cache_hits"] += 1

        ordered_ids  = list(candidate["ordered_product_ids"])
        docs         = _hydrate(ordered_ids)
        response_meta = {
            "cache_version":       2,
            "cache_hit_source":    "LEXICAL_NEAR",
            "source_query":        candidate["normalized_query"],
            "lexical_similarity":  accept_stats["trgm_score"],
            "shared_tokens":       accept_stats.get("shared_tokens", []),
            "shared_count":        accept_stats.get("shared_count", 0),
            "token_overlap_ratio": accept_stats.get("token_overlap_ratio", 0.0),
        }

        # Write-back: fresh ACTIVE entry for incoming query (bypasses lexical-near next time)
        _l2_cleanup_expired()
        _l2_put(
            normalized, query_hash, filter_hash, sort_key,
            page_number, page_limit,
            ordered_ids, len(docs), response_meta,
            query_tokens=incoming_tokens,
            cache_version=2,
        )
        _l1_put(
            query_hash, ordered_ids, len(docs), response_meta,
            freshness_status="ACTIVE",
        )

        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "Cache LEXICAL_NEAR HIT — normalized=%r source=%r "
            "trgm_score=%.4f cand_freshness=%s results=%d latency_ms=%d",
            normalized,
            candidate["normalized_query"],
            accept_stats["trgm_score"],
            cand_eff,
            len(docs),
            elapsed_ms,
        )
        return {
            "query": q, "total": len(docs), "results": docs,
            "cache_hit_source": "LEXICAL_NEAR", "freshness_status": "ACTIVE",
        }

    # ── Step 6: Compute embedding (once; shared for semantic + hybrid) ────────
    try:
        t_embed   = time.monotonic()
        embedding = model.encode(normalized).tolist()
        vec_str   = _vec_str(embedding)
        embed_ms  = int((time.monotonic() - t_embed) * 1000)
        _metrics["embeddings_computed"] += 1
    except Exception as exc:
        logger.error("Embedding computation failed: %s", exc)
        raise HTTPException(status_code=503, detail="Embedding service unavailable")

    # ── Step 6 (cont): Semantic cache lookup ─────────────────────────────────
    t_sem_lookup   = time.monotonic()
    sem_candidates = _semantic_get(vec_str, filter_hash, sort_key, page_number, page_limit)
    sem_lookup_ms  = int((time.monotonic() - t_sem_lookup) * 1000)

    logger.info(
        "Semantic candidates — normalized=%r count=%d lookup_ms=%d",
        normalized, len(sem_candidates), sem_lookup_ms,
    )

    for sem_candidate in sem_candidates:
        _metrics["semantic_candidates_seen"] += 1

        # Phase 4: compute effective freshness of this semantic candidate
        cand_eff = _effective_freshness(
            sem_candidate.get("freshness_status", "ACTIVE"),
            sem_candidate.get("soft_expires_at"),
        )
        if cand_eff == "HARD_EXPIRED":
            _metrics["hard_expired_rejects"] += 1
            continue

        accepted, sem_stats = _accept_semantic_candidate(incoming_tokens, sem_candidate)
        if not accepted:
            _metrics["semantic_rejects"] += 1
            logger.info(
                "Semantic REJECT — normalized=%r candidate=%r similarity=%.4f reason=%s",
                normalized,
                sem_candidate["normalized_query"],
                sem_stats.get("similarity", 0.0),
                sem_stats.get("reject_reason", "unknown"),
            )
            continue

        _metrics["semantic_hits"] += 1
        if cand_eff == "SOFT_EXPIRED":
            _metrics["soft_expired_cache_hits"] += 1
        else:
            _metrics["active_cache_hits"] += 1

        ordered_ids = list(sem_candidate["ordered_product_ids"])
        docs        = _hydrate(ordered_ids)

        sem_meta = {
            "source_query":  sem_candidate["normalized_query"],
            "similarity":    sem_stats["similarity"],
            "band":          sem_stats.get("band", "unknown"),
            "shared_tokens": sem_stats.get("shared_tokens", []),
            "shared_count":  sem_stats.get("shared_count", 0),
            "lookup_ms":     sem_lookup_ms,
        }
        response_meta = {
            "cache_version":       3,
            "cache_hit_source":    "SEMANTIC",
            "source_query":        sem_candidate["normalized_query"],
            "semantic_similarity": sem_stats["similarity"],
            "band":                sem_stats.get("band", "unknown"),
        }

        # Write-back: fresh ACTIVE entry for incoming query with its embedding
        _l2_cleanup_expired()
        _l2_put(
            normalized, query_hash, filter_hash, sort_key,
            page_number, page_limit,
            ordered_ids, len(docs), response_meta,
            query_tokens=incoming_tokens,
            cache_version=3,
            query_embedding_str=vec_str,
            semantic_source_query=sem_candidate["normalized_query"],
            semantic_similarity=sem_stats["similarity"],
            semantic_meta=sem_meta,
        )
        _l1_put(
            query_hash, ordered_ids, len(docs), response_meta,
            freshness_status="ACTIVE",
        )

        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "Cache SEMANTIC HIT — normalized=%r source=%r similarity=%.4f "
            "band=%s cand_freshness=%s results=%d embed_ms=%d sem_lookup_ms=%d total_ms=%d",
            normalized,
            sem_candidate["normalized_query"],
            sem_stats["similarity"],
            sem_stats.get("band", "unknown"),
            cand_eff,
            len(docs),
            embed_ms,
            sem_lookup_ms,
            elapsed_ms,
        )
        return {
            "query": q, "total": len(docs), "results": docs,
            "cache_hit_source": "SEMANTIC", "freshness_status": "ACTIVE",
        }

    # ── Step 7: Cache miss — run full hybrid search ───────────────────────────
    _metrics["misses"] += 1
    try:
        t_search = time.monotonic()
        with get_db_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
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
            "cache_version": 5,
            "search_mode":   "hybrid",
            "embed_ms":      embed_ms,
            "search_ms":     search_ms,
        }

        now_utc     = datetime.now(timezone.utc)
        hard_exp_dt = now_utc + timedelta(seconds=L2_HARD_TTL_SECONDS)

        _l2_cleanup_expired()
        _l2_put(
            normalized, query_hash, filter_hash, sort_key,
            page_number, page_limit,
            ordered_ids, result_count, response_meta,
            query_tokens=incoming_tokens,
            cache_version=5,
            query_embedding_str=vec_str,
        )
        _l1_put(
            query_hash, ordered_ids, result_count, response_meta,
            hard_expires_at=hard_exp_dt,
            freshness_status="ACTIVE",
        )

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
            "freshness_status": "ACTIVE",
        }

    except psycopg2.Error as exc:
        logger.error("DB error during search: %s", exc)
        raise HTTPException(status_code=503, detail="Search temporarily unavailable")
    except Exception as exc:
        logger.error("Unexpected error during search: %s", exc)
        raise HTTPException(status_code=500, detail="Internal search error")


@app.post("/internal/invalidate")
def invalidate(body: InvalidateRequest):
    """
    Event-driven cache invalidation endpoint.
    Called by the ingestion pipeline when a product is updated.

    Marks matching query_cache rows as SOFT_EXPIRED or HARD_EXPIRED,
    evicts matching L1 entries immediately, and emits a PostgreSQL NOTIFY.
    """
    rows_updated = _invalidate_product(
        product_id=body.product_id,
        event_type=body.event_type,
        changed_fields=body.changed_fields,
    )
    severity = _invalidation_severity(body.event_type, body.changed_fields)
    return {
        "product_id":    body.product_id,
        "event_type":    body.event_type,
        "target_status": severity,
        "rows_updated":  rows_updated,
    }


@app.get("/health")
def health():
    return {"status": "up"}


@app.get("/cache/stats")
def cache_stats():
    """Diagnostics: cache hit/miss counters, L1 occupancy, Phase 2/3/4 metrics."""
    now       = time.monotonic()
    now_wall  = datetime.now(timezone.utc)
    l1_active = sum(
        1 for e in _l1_cache.values()
        if now <= e.expires_at
        and now_wall < (e.hard_expires_at if e.hard_expires_at.tzinfo
                        else e.hard_expires_at.replace(tzinfo=timezone.utc))
        and e.freshness_status != "HARD_EXPIRED"
    )
    total_cache_hits = (
        _metrics["l1_hits"]
        + _metrics["l2_hits"]
        + _metrics["lexical_near_hits"]
        + _metrics["semantic_hits"]
    )
    total_requests = total_cache_hits + _metrics["misses"]
    return {
        # L1
        "l1_size_active":              l1_active,
        "l1_size_total":               len(_l1_cache),
        "l1_ttl_seconds":              L1_TTL_SECONDS,
        # L2 TTLs (Phase 4)
        "l2_soft_ttl_seconds":         L2_SOFT_TTL_SECONDS,
        "l2_hard_ttl_seconds":         L2_HARD_TTL_SECONDS,
        # Lexical-near config (Phase 2)
        "lexical_near_threshold":      LEXICAL_NEAR_SIMILARITY_THRESHOLD,
        "lexical_near_max_cands":      LEXICAL_NEAR_MAX_CANDIDATES,
        "lexical_near_min_tokens":     LEXICAL_NEAR_MIN_SHARED_TOKENS,
        # Semantic config (Phase 3)
        "semantic_strong_accept":      SEMANTIC_STRONG_ACCEPT,
        "semantic_borderline_low":     SEMANTIC_BORDERLINE_LOW,
        "semantic_max_candidates":     SEMANTIC_MAX_CANDIDATES,
        # All counters
        **_metrics,
        # Derived
        "total_requests":              total_requests,
        "embedding_skips":             _metrics["lexical_near_hits"],
        "cache_hit_rate":              round(total_cache_hits / max(total_requests, 1), 4),
    }
