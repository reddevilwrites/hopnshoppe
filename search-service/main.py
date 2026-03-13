"""
search-service — Hybrid Semantic Search with L1 + L2 Exact Cache + Lexical-Near Cache + Semantic Cache
======================================================================================================

GET /search?q=...&limit=...

Returns denormalized product documents directly from the search_index table.
No downstream catalog-service call is made per result.

Cache Flow
----------
  L1 (in-process, TTL=2 min)
    → L2 (Postgres query_cache exact, TTL=10 min)
        → Lexical-near (Postgres query_cache, pg_trgm similarity, TTL from existing rows)
            → Semantic cache (Postgres query_cache, vector cosine similarity over query embeddings)
                → hybrid search on search_index   [embedding computed once; shared by semantic + storage]
                    → cache write (L2 + L1, with query_embedding)
                    → hydrated response

On any cache hit, current denormalized_doc rows are bulk-fetched from
search_index in one query — cached product IDs are the safe reuse unit.

Ranking (on cache MISS only)
-----------------------------
  70% vector cosine similarity  (all-MiniLM-L6-v2, 384-dim)
  30% PostgreSQL ts_rank_cd     (full-text, GIN-indexed tsvector)

Lexical-Near Acceptance (Phase 2)
-----------------------------------
  A candidate cache entry is reused only when ALL of the following hold:
    1. pg_trgm similarity >= LEXICAL_NEAR_SIMILARITY_THRESHOLD (default 0.76)
    2. Incoming query has >= 2 significant tokens  (1-word queries too ambiguous)
    3. At least LEXICAL_NEAR_MIN_SHARED_TOKENS significant tokens in common
    4. filter_hash, sort_key, page_number, page_limit match exactly
    5. Candidate row is non-expired and ACTIVE

Semantic Cache Acceptance (Phase 3)
--------------------------------------
  Matches the incoming query embedding against embeddings of previously executed
  queries stored in query_cache.  Embedding is computed after exact + lexical-near
  miss and reused for both semantic lookup and full hybrid search.

  Thresholds:
    strong accept : similarity >= 0.88 — no extra guardrails
    borderline    : 0.84 <= similarity < 0.88 — price-intent + token guardrails
    hard reject   : similarity < 0.84

  On hit: incoming query is written to exact cache with its embedding so the
  next identical search hits L2 directly.
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

# Lexical-near cache constants (Phase 2)
# Threshold: 0.76 — conservative starting point.
#   - pg_trgm similarity is character-trigram based (not semantic).
#   - 0.76 rejects "cheap boots" ↔ "premium leather boots" (0.45 similarity)
#     while accepting "cheap waterproof boots" ↔ "waterproof boots under 50"
#     (typically 0.78–0.85 similarity).
#   - Raise toward 0.85 if too many false positives are seen in production logs.
LEXICAL_NEAR_SIMILARITY_THRESHOLD = 0.76
LEXICAL_NEAR_MAX_CANDIDATES        = 5     # max rows fetched from query_cache per request
LEXICAL_NEAR_MIN_SHARED_TOKENS     = 2     # minimum significant tokens that must overlap

# Semantic cache constants (Phase 3)
# strong accept : similarity >= 0.88 — accepted without extra token guardrails
# borderline    : 0.84 <= similarity < 0.88 — extra price-intent + token guardrails apply
# hard reject   : similarity < 0.84
SEMANTIC_STRONG_ACCEPT  = 0.88
SEMANTIC_BORDERLINE_LOW = 0.84
SEMANTIC_MAX_CANDIDATES = 5     # top-N candidates from query_cache per request

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

app = FastAPI(title="search-service", version="4.0.0")

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
# Tokeniser (Phase 2) — lightweight, deterministic, no external dependencies
# ---------------------------------------------------------------------------
# Common English stopwords to exclude from the token-overlap guardrail.
# Kept short and focused on words that carry no product-category signal.
_STOPWORDS: frozenset = frozenset({
    "a", "an", "the", "and", "or", "of", "in", "to", "for",
    "with", "on", "at", "by", "is", "it", "its", "as", "be",
    "are", "was", "were", "that", "this", "from", "into", "up",
    "under", "over", "my", "me", "i", "do", "not", "no",
})

# Split on whitespace and common punctuation — keeps alphanumeric tokens only.
_TOKEN_SPLIT = re.compile(r"[\s\-_/.,;:!?&'\"()\[\]{}]+")

# Semantic intent-conflict term sets (Phase 3 guardrails).
# A token set flagged BUDGET and a candidate flagged PREMIUM are rejected (and vice-versa).
_BUDGET_TERMS  = frozenset({"cheap", "budget", "affordable", "inexpensive", "discount", "bargain"})
_PREMIUM_TERMS = frozenset({"premium", "luxury", "expensive", "high-end", "designer", "deluxe", "exclusive"})


def _tokenize(text: str) -> list:
    """
    Tokenise a normalised query string for the token-overlap guardrail.

    Rules:
      - lowercase (caller should already have normalised, but harmless to repeat)
      - split on whitespace and simple punctuation
      - drop empty tokens
      - drop single-character tokens (too noisy for overlap scoring)
      - drop stopwords

    Returns a list of significant token strings (may be empty).

    Examples:
      "cheap waterproof boots"    → ["cheap", "waterproof", "boots"]
      "waterproof boots under 50" → ["waterproof", "boots", "50"]
      "running shoes"             → ["running", "shoes"]
    """
    return [
        t for t in _TOKEN_SPLIT.split(text.lower())
        if t and len(t) > 1 and t not in _STOPWORDS
    ]


def _has_price_intent_conflict(tokens_a: list, tokens_b: list) -> bool:
    """
    Return True if one token set signals budget intent and the other signals
    premium intent — a semantic cache hit between these would return wrong results.

    Examples:
      ["cheap", "boots"] vs ["premium", "boots"]    → True  (conflict)
      ["waterproof", "boots"] vs ["affordable", "boots"] → False (no conflict)
    """
    set_a, set_b = set(tokens_a), set(tokens_b)
    a_budget  = bool(set_a & _BUDGET_TERMS)
    a_premium = bool(set_a & _PREMIUM_TERMS)
    b_budget  = bool(set_b & _BUDGET_TERMS)
    b_premium = bool(set_b & _PREMIUM_TERMS)
    return (a_budget and b_premium) or (a_premium and b_budget)


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
    "l1_hits":                  0,
    "l2_hits":                  0,
    "lexical_near_hits":        0,
    "lexical_near_rejects":     0,
    "semantic_hits":            0,
    "semantic_rejects":         0,
    "semantic_candidates_seen": 0,
    "embeddings_computed":      0,
    "misses":                   0,
    "writes":                   0,
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
    query_tokens: Optional[list] = None,
    cache_version: int = 2,
    query_embedding_str: Optional[str] = None,       # Phase 3: "[x,y,…]" pgvector string
    semantic_source_query: Optional[str] = None,      # Phase 3
    semantic_similarity: Optional[float] = None,      # Phase 3
    semantic_meta: Optional[dict] = None,             # Phase 3
) -> None:
    """Upsert a cache entry.  Silently ignores DB errors (non-blocking path).

    query_embedding_str: pass the raw "[x,y,…]" string; SQL casts it via ::vector.
      Pass None to leave the column NULL (older rows / lexical-near write-backs).
      NULL::vector is valid PostgreSQL — psycopg2 renders None as NULL.
    """
    expires_at    = datetime.now(timezone.utc) + timedelta(seconds=L2_TTL_SECONDS)
    tokens_json   = json.dumps(query_tokens) if query_tokens is not None else None
    sem_meta_json = json.dumps(semantic_meta) if semantic_meta is not None else None
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO query_cache (
                    normalized_query, query_hash, filter_hash, sort_key,
                    page_number, page_limit,
                    ordered_product_ids, result_count, response_meta,
                    expires_at, status,
                    lexical_signature, query_tokens, cache_version,
                    query_embedding, semantic_source_query, semantic_similarity, semantic_meta
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ACTIVE',
                          %s, %s, %s,
                          %s::vector, %s, %s, %s)
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
                    query_embedding       = COALESCE(EXCLUDED.query_embedding,      query_cache.query_embedding),
                    semantic_source_query = COALESCE(EXCLUDED.semantic_source_query, query_cache.semantic_source_query),
                    semantic_similarity   = COALESCE(EXCLUDED.semantic_similarity,   query_cache.semantic_similarity),
                    semantic_meta         = COALESCE(EXCLUDED.semantic_meta,         query_cache.semantic_meta)
                """,
                (
                    normalized_query, query_hash, filter_hash, sort_key,
                    page_number, page_limit,
                    ordered_product_ids, result_count,
                    json.dumps(response_meta), expires_at,
                    normalized_query,       # lexical_signature = normalized_query for now
                    tokens_json,
                    cache_version,
                    query_embedding_str,    # None → NULL::vector (valid)
                    semantic_source_query,
                    semantic_similarity,
                    sem_meta_json,
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
# Phase 2 — Lexical-near cache lookup
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

    Uses the pg_trgm `%` operator (requires pg_trgm extension and the GIN
    trigram index on query_cache.normalized_query).

    Returns a list of dicts ordered by descending trgm_score; up to
    LEXICAL_NEAR_MAX_CANDIDATES rows.
    """
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT normalized_query,
                       ordered_product_ids,
                       result_count,
                       response_meta,
                       query_tokens,
                       similarity(normalized_query, %s) AS trgm_score
                FROM query_cache
                WHERE normalized_query %% %s
                  AND filter_hash = %s
                  AND sort_key    = %s
                  AND page_number = %s
                  AND page_limit  = %s
                  AND expires_at  > now()
                  AND status      = 'ACTIVE'
                ORDER BY similarity(normalized_query, %s) DESC
                LIMIT %s
                """,
                (
                    normalized_query,               # similarity() first arg
                    normalized_query,               # %% operator RHS
                    filter_hash,
                    sort_key,
                    page_number,
                    page_limit,
                    normalized_query,               # similarity() ORDER BY arg
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
    stats always contains trgm_score; on rejection also contains reject_reason.
    On acceptance also contains shared_tokens, shared_count, token_overlap_ratio.

    Guardrails (all must pass):
      1. trgm_score >= LEXICAL_NEAR_SIMILARITY_THRESHOLD
      2. incoming query must have >= 2 significant tokens
      3. shared significant tokens >= LEXICAL_NEAR_MIN_SHARED_TOKENS
    """
    trgm_score = float(candidate.get("trgm_score", 0.0))
    candidate_normalized = candidate["normalized_query"]

    # Derive candidate tokens: prefer stored query_tokens, fall back to live tokenisation.
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
        "trgm_score": round(trgm_score, 4),
        "candidate_normalized": candidate_normalized,
    }

    # Guardrail 1: trigram similarity floor
    if trgm_score < LEXICAL_NEAR_SIMILARITY_THRESHOLD:
        stats["reject_reason"] = "low_trgm_similarity"
        return False, stats

    # Guardrail 2: single-token queries are too ambiguous for lexical-near reuse
    if len(incoming_tokens) <= 1:
        stats["reject_reason"] = "single_token_query"
        return False, stats

    # Guardrail 3: token overlap
    shared = set(incoming_tokens) & set(candidate_tokens)
    shared_count = len(shared)
    stats["shared_tokens"] = sorted(shared)
    stats["shared_count"] = shared_count
    stats["token_overlap_ratio"] = round(
        shared_count / max(len(incoming_tokens), 1), 3
    )

    if shared_count < LEXICAL_NEAR_MIN_SHARED_TOKENS:
        stats["reject_reason"] = "insufficient_token_overlap"
        return False, stats

    return True, stats


# ---------------------------------------------------------------------------
# Phase 3 — Semantic cache lookup
# ---------------------------------------------------------------------------
def _semantic_get(
    embedding_str: str,
    filter_hash: str,
    sort_key: str,
    page_number: int,
    page_limit: int,
) -> list:
    """
    Retrieve top-N semantically similar cache candidates using an exact cosine
    scan over query_cache.query_embedding (VECTOR(384)).

    Uses pgvector's <=> operator (cosine distance = 1 − cosine similarity).
    Results are ordered by ascending distance (most similar first).
    Application code in _accept_semantic_candidate applies acceptance logic.

    Exact scan is used for Phase 3 because query_cache is small (bounded by
    L2 TTL eviction).  Enable the HNSW index in init.sql when the table exceeds
    ~10 k active rows and lookup latency becomes measurable.

    Only considers rows that are:
      - non-expired and ACTIVE
      - semantic_cache_enabled = TRUE
      - query_embedding IS NOT NULL
      - filter_hash, sort_key, page_number, page_limit exact match

    Returns a list of dicts with keys:
      normalized_query, ordered_product_ids, result_count, query_tokens,
      cosine_distance, semantic_similarity
    """
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    normalized_query,
                    ordered_product_ids,
                    result_count,
                    query_tokens,
                    query_embedding <=> %s::vector                  AS cosine_distance,
                    1 - (query_embedding <=> %s::vector)            AS semantic_similarity
                FROM query_cache
                WHERE query_embedding        IS NOT NULL
                  AND status                 = 'ACTIVE'
                  AND expires_at             > now()
                  AND semantic_cache_enabled = TRUE
                  AND filter_hash            = %s
                  AND COALESCE(sort_key, '') = COALESCE(%s, '')
                  AND page_number            = %s
                  AND page_limit             = %s
                ORDER BY query_embedding <=> %s::vector ASC
                LIMIT %s
                """,
                (
                    embedding_str,  # cosine_distance column
                    embedding_str,  # semantic_similarity column
                    filter_hash,
                    sort_key,
                    page_number,
                    page_limit,
                    embedding_str,  # ORDER BY
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

    Similarity thresholds:
      strong accept  : similarity >= 0.88 — accepted without extra token guardrails
      borderline     : 0.84 <= similarity < 0.88 — price-intent + token guardrails
      hard reject    : similarity < 0.84

    Guardrails applied in ALL zones:
      - No price-intent conflict (budget/cheap terms vs premium/luxury terms)

    Borderline-only guardrails:
      - shared significant tokens >= 2 for multi-word incoming queries

    Phase 4 extensions: brand conflict, category conflict detection.
    """
    similarity = float(candidate.get("semantic_similarity", 0.0))
    candidate_normalized = candidate["normalized_query"]

    stats = {
        "similarity": round(similarity, 4),
        "candidate_normalized": candidate_normalized,
    }

    # Hard floor
    if similarity < SEMANTIC_BORDERLINE_LOW:
        stats["reject_reason"] = "low_similarity"
        return False, stats

    # Derive candidate tokens for guardrail checks
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

    # Price-intent conflict check (applies in all zones)
    if _has_price_intent_conflict(incoming_tokens, candidate_tokens):
        stats["reject_reason"] = "price_intent_conflict"
        return False, stats

    # Strong accept zone — no further guardrails
    if similarity >= SEMANTIC_STRONG_ACCEPT:
        stats["band"] = "strong"
        return True, stats

    # Borderline zone — require minimum shared token count for multi-word queries
    shared = set(incoming_tokens) & set(candidate_tokens)
    shared_count = len(shared)
    stats["shared_tokens"] = sorted(shared)
    stats["shared_count"] = shared_count

    if len(incoming_tokens) > 1 and shared_count < 2:
        stats["reject_reason"] = "borderline_insufficient_token_overlap"
        return False, stats

    stats["band"] = "borderline"
    return True, stats


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

    # Tokenise once — used by lexical-near acceptance, semantic guardrails, and cache rows.
    incoming_tokens = _tokenize(normalized)

    logger.info(
        "Search request — q=%r normalized=%r tokens=%s limit=%d query_hash=%.8s…",
        q, normalized, incoming_tokens, limit, query_hash,
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

    # ── Step 5: Lexical-near cache lookup ────────────────────────────────────
    # Retrieve top similar candidates from query_cache using pg_trgm, then
    # apply application-level acceptance guardrails.  The embedding call and
    # hybrid search are skipped entirely on a successful lexical-near hit.
    candidates = _lexical_near_get(
        normalized, filter_hash, sort_key, page_number, page_limit
    )

    logger.info(
        "Lexical-near candidates — normalized=%r count=%d",
        normalized, len(candidates),
    )

    for candidate in candidates:
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

        # Accepted — reuse candidate ordered_product_ids
        _metrics["lexical_near_hits"] += 1
        ordered_ids  = list(candidate["ordered_product_ids"])
        result_count = candidate["result_count"]

        docs = _hydrate(ordered_ids)

        response_meta = {
            "cache_version":       2,
            "cache_hit_source":    "LEXICAL_NEAR",
            "source_query":        candidate["normalized_query"],
            "lexical_similarity":  accept_stats["trgm_score"],
            "shared_tokens":       accept_stats.get("shared_tokens", []),
            "shared_count":        accept_stats.get("shared_count", 0),
            "token_overlap_ratio": accept_stats.get("token_overlap_ratio", 0.0),
        }

        # Write-back: create an exact cache entry for the incoming query so
        # subsequent identical requests hit L2/L1 directly, bypassing lexical-near.
        # No embedding computed here — embedding_str stays None for lexical hits.
        _l2_cleanup_expired()
        _l2_put(
            normalized, query_hash, filter_hash, sort_key,
            page_number, page_limit,
            ordered_ids, len(docs), response_meta,
            query_tokens=incoming_tokens,
            cache_version=2,
        )
        _l1_put(query_hash, ordered_ids, len(docs), response_meta)

        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "Cache LEXICAL_NEAR HIT — normalized=%r source=%r "
            "trgm_score=%.4f shared_tokens=%s results=%d "
            "embedding_skipped=True latency_ms=%d",
            normalized,
            candidate["normalized_query"],
            accept_stats["trgm_score"],
            accept_stats.get("shared_tokens", []),
            len(docs),
            elapsed_ms,
        )
        return {
            "query":            q,
            "total":            len(docs),
            "results":          docs,
            "cache_hit_source": "LEXICAL_NEAR",
        }

    # ── Step 6: Compute embedding ────────────────────────────────────────────
    # Computed once here — reused for both semantic lookup AND hybrid search
    # so we never call model.encode() twice per request.
    try:
        t_embed  = time.monotonic()
        embedding = model.encode(normalized).tolist()
        vec_str   = _vec_str(embedding)
        embed_ms  = int((time.monotonic() - t_embed) * 1000)
        _metrics["embeddings_computed"] += 1
    except Exception as exc:
        logger.error("Embedding computation failed: %s", exc)
        raise HTTPException(status_code=503, detail="Embedding service unavailable")

    # ── Step 6 (cont): Semantic cache lookup ─────────────────────────────────
    t_sem_lookup  = time.monotonic()
    sem_candidates = _semantic_get(vec_str, filter_hash, sort_key, page_number, page_limit)
    sem_lookup_ms  = int((time.monotonic() - t_sem_lookup) * 1000)

    logger.info(
        "Semantic candidates — normalized=%r count=%d lookup_ms=%d",
        normalized, len(sem_candidates), sem_lookup_ms,
    )

    for sem_candidate in sem_candidates:
        _metrics["semantic_candidates_seen"] += 1
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

        # Accepted — reuse candidate ordered_product_ids; bulk-fetch fresh docs
        _metrics["semantic_hits"] += 1
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

        # Write-back: upsert exact cache row for incoming query with its embedding
        # so the next identical search hits L2/L1 directly.
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
        _l1_put(query_hash, ordered_ids, len(docs), response_meta)

        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "Cache SEMANTIC HIT — normalized=%r source=%r similarity=%.4f "
            "band=%s results=%d embed_ms=%d sem_lookup_ms=%d total_ms=%d",
            normalized,
            sem_candidate["normalized_query"],
            sem_stats["similarity"],
            sem_stats.get("band", "unknown"),
            len(docs),
            embed_ms,
            sem_lookup_ms,
            elapsed_ms,
        )
        return {
            "query":            q,
            "total":            len(docs),
            "results":          docs,
            "cache_hit_source": "SEMANTIC",
        }

    # ── Step 7: Cache miss — run full hybrid search ───────────────────────────
    # vec_str and embed_ms already computed above; no redundant encoding here.
    _metrics["misses"] += 1
    try:
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
            "cache_version": 3,
            "search_mode":   "hybrid",
            "embed_ms":      embed_ms,
            "search_ms":     search_ms,
        }

        # Persist to L2 with query_embedding (enables future semantic hits),
        # then warm L1.
        _l2_cleanup_expired()
        _l2_put(
            normalized, query_hash, filter_hash, sort_key,
            page_number, page_limit,
            ordered_ids, result_count, response_meta,
            query_tokens=incoming_tokens,
            cache_version=3,
            query_embedding_str=vec_str,
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
    """Diagnostics: cache hit/miss counters, L1 occupancy, Phase 2/3 metrics."""
    now = time.monotonic()
    l1_active = sum(1 for e in _l1_cache.values() if now <= e.expires_at)
    total_cache_hits = (
        _metrics["l1_hits"]
        + _metrics["l2_hits"]
        + _metrics["lexical_near_hits"]
        + _metrics["semantic_hits"]
    )
    total_requests = total_cache_hits + _metrics["misses"]
    return {
        # L1
        "l1_size_active":           l1_active,
        "l1_size_total":            len(_l1_cache),
        "l1_ttl_seconds":           L1_TTL_SECONDS,
        # L2
        "l2_ttl_seconds":           L2_TTL_SECONDS,
        # Lexical-near config (Phase 2)
        "lexical_near_threshold":   LEXICAL_NEAR_SIMILARITY_THRESHOLD,
        "lexical_near_max_cands":   LEXICAL_NEAR_MAX_CANDIDATES,
        "lexical_near_min_tokens":  LEXICAL_NEAR_MIN_SHARED_TOKENS,
        # Semantic config (Phase 3)
        "semantic_strong_accept":   SEMANTIC_STRONG_ACCEPT,
        "semantic_borderline_low":  SEMANTIC_BORDERLINE_LOW,
        "semantic_max_candidates":  SEMANTIC_MAX_CANDIDATES,
        # Counters
        **_metrics,
        # Derived
        "total_requests":           total_requests,
        "embedding_skips":          _metrics["lexical_near_hits"],
        "cache_hit_rate":           round(total_cache_hits / max(total_requests, 1), 4),
    }
