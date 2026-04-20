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
import math
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import psycopg2
import psycopg2.extras
from psycopg2 import pool as psycopg2_pool
from contextlib import contextmanager, asynccontextmanager
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from sentence_transformers import SentenceTransformer

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
class _JsonLogFormatter(logging.Formatter):
    """Emit structured JSON logs with trace/span correlation when available."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": "search-service",
        }

        otel_trace = globals().get("trace")
        if otel_trace is not None:
            try:
                span = otel_trace.get_current_span()
                ctx = span.get_span_context()
                if ctx is not None and ctx.is_valid:
                    payload["trace_id"] = format(ctx.trace_id, "032x")
                    payload["span_id"] = format(ctx.span_id, "016x")
            except Exception:
                pass

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True)


_handler = logging.StreamHandler()
_handler.setFormatter(_JsonLogFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
logger = logging.getLogger("search-service")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SEARCH_DB_HOST     = os.environ.get("SEARCH_DB_HOST", "search-db")
SEARCH_DB_PORT     = int(os.environ.get("SEARCH_DB_PORT", "5432"))
SEARCH_DB_NAME     = os.environ.get("SEARCH_DB_NAME", "search_db")
SEARCH_DB_USER     = os.environ.get("SEARCH_DB_USER", "postgres")
SEARCH_DB_PASSWORD = os.environ["SEARCH_DB_PASSWORD"]

EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

# ── Kafka consumer configuration ─────────────────────────────────────────────
# KAFKA_BOOTSTRAP_SERVERS is injected via env (see docker-compose.yml).
# KAFKA_GROUP_ID must differ from the ingestion-worker group so both consumers
# receive every message independently — they serve different purposes.
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC     = "product-updates"
KAFKA_GROUP_ID  = "search-service-cache-invalidator"

# ── Eureka registration configuration ────────────────────────────────────────
# EUREKA_URI is injected via env (see docker-compose.yml).
# Uppercase app name is the Eureka convention; lb://search-service resolution
# in the gateway is case-insensitive.
EUREKA_URI           = os.environ.get("EUREKA_URI", "http://discovery-server:8761/eureka/")
EUREKA_APP_NAME      = "SEARCH-SERVICE"
EUREKA_INSTANCE_HOST = os.environ.get("EUREKA_HOSTNAME", "search-service")
EUREKA_PORT          = 8085
EUREKA_INSTANCE_ID   = f"{EUREKA_INSTANCE_HOST}:{EUREKA_PORT}"
EUREKA_HEARTBEAT_S   = 30   # PUT every 30 s (Eureka default lease-renewal interval)
EUREKA_LEASE_S       = 90   # deregister after 3 missed heartbeats

# ── Cache TTL constants ─────────────────────────────────────────────────────
L1_TTL_SECONDS      = 120     # 2 min — hot in-process cache (must be < soft TTL)
L1_MAX_ENTRIES      = 500     # evict oldest 10% when ceiling is reached
L2_SOFT_TTL_SECONDS = 600     # 10 min — ACTIVE window; SOFT_EXPIRED after this
L2_HARD_TTL_SECONDS = 3600    # 60 min — hard barrier; HARD_EXPIRED rows never served
QUERY_CACHE_MAX_ROWS = int(os.environ.get("QUERY_CACHE_MAX_ROWS", "50000"))

# ── Adaptive TTL constants (Phase 5) ────────────────────────────────────────
# soft_ttl = min(L2_SOFT_TTL_SECONDS * (1 + log10(max(hit_count, 1))),
#                L2_HARD_TTL_SECONDS)
# Floor  = L2_SOFT_TTL_SECONDS — cold entries always get the base window.
# Ceiling = L2_HARD_TTL_SECONDS — soft never exceeds hard.
ADAPTIVE_TTL_ENABLED = True     # set False to revert to fixed TTL without redeploy
ADAPTIVE_TTL_CEILING = L2_HARD_TTL_SECONDS   # 3600s — must equal hard TTL

# ── Lexical-near constants (Phase 2) ────────────────────────────────────────
LEXICAL_NEAR_SIMILARITY_THRESHOLD = 0.76
LEXICAL_NEAR_MAX_CANDIDATES       = 5
LEXICAL_NEAR_MIN_SHARED_TOKENS    = 2

# ── Semantic cache constants (Phase 3) ──────────────────────────────────────
SEMANTIC_STRONG_ACCEPT  = 0.88
SEMANTIC_BORDERLINE_LOW = 0.84
SEMANTIC_MAX_CANDIDATES = 5

# ── Cache eligibility (all phases) ──────────────────────────────────────────
# Queries shorter than this are served directly from hybrid search and never
# written to the cache. Single-char and tiny queries produce meaningless
# embeddings that pollute the semantic candidate pool.
MIN_CACHEABLE_QUERY_CHARS = 3

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
# Distributed tracing — initialised before model load and pool creation
# ---------------------------------------------------------------------------
class _NoOpSpan:
    """Minimal no-op span used when OTel is unavailable."""
    def set_attribute(self, *a, **kw): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass


def _init_tracing() -> bool:
    """
    Set up OpenTelemetry tracing. Returns True if tracing is active.
    A missing endpoint or ImportError leaves the service fully functional
    with no-op spans — the search path is never blocked by tracing failures.
    """
    if not _OTEL_AVAILABLE:
        logger.info("OTel packages not installed — tracing disabled")
        return False
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set — tracing disabled")
        return False
    try:
        service_name = os.environ.get("OTEL_SERVICE_NAME", "search-service")
        resource     = Resource({"service.name": service_name})
        provider     = TracerProvider(resource=resource)
        exporter     = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        Psycopg2Instrumentor().instrument()
        logger.info("OTel tracing enabled — endpoint=%s service=%s", endpoint, service_name)
        return True
    except Exception as exc:
        logger.warning("OTel tracing init failed (non-fatal): %s", exc)
        return False


_tracing_enabled = _init_tracing()
_tracer = trace.get_tracer("search-service") if _OTEL_AVAILABLE else None


def _start_span(name: str):
    """Return a real OTel span or a no-op when tracing is disabled."""
    if _tracer is not None:
        return _tracer.start_as_current_span(name)
    return _NoOpSpan()


# ---------------------------------------------------------------------------
# Startup — load embedding model and connect to search-db (with retry)
# ---------------------------------------------------------------------------
logger.info("Loading embedding model '%s' …", EMBED_MODEL)
model = SentenceTransformer(EMBED_MODEL)
MODEL_EMBED_DIM = int(model.get_sentence_embedding_dimension())
logger.info("Embedding model dimension resolved to %d", MODEL_EMBED_DIM)


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


def _get_vector_dimension(cur, table_name: str, column_name: str) -> Optional[int]:
    """
    Return the pgvector dimension recorded in pg_attribute.atttypmod.
    None means the column does not exist.
    """
    cur.execute(
        """
        SELECT atttypmod
        FROM pg_attribute
        WHERE attrelid = %s::regclass
          AND attname   = %s
          AND attnum    > 0
        """,
        (table_name, column_name),
    )
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _rebuild_search_index_embeddings(conn) -> int:
    """
    Recompute search_index embeddings in place after a vector dimension change.
    This is only used when the persisted schema does not match the loaded model.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT product_id, search_text FROM search_index ORDER BY product_id")
        rows = cur.fetchall()

    if not rows:
        logger.info("search_index rebuild skipped — no rows found")
        return 0

    batch_size = 50
    processed = 0
    logger.warning(
        "Rebuilding search_index embeddings for %d products with model '%s' (%d-dim)",
        len(rows), EMBED_MODEL, MODEL_EMBED_DIM,
    )

    with conn.cursor() as cur:
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            texts = [r[1] for r in batch]
            embeddings = model.encode(texts, batch_size=batch_size, show_progress_bar=False)
            for (product_id, _), emb in zip(batch, embeddings):
                cur.execute(
                    "UPDATE search_index SET embedding = %s::vector WHERE product_id = %s",
                    (_vec_str(emb.tolist()), product_id),
                )
            processed += len(batch)

    logger.info("search_index embedding rebuild completed — processed=%d", processed)
    return processed


def _ensure_vector_schema_and_reset_semantic_cache() -> None:
    """
    Repair persisted pgvector schema drift against the currently loaded model.

    Why this exists:
      - init.sql only runs on first database initialization.
      - when the search-db Docker volume already exists, switching from a
        384-dim model to a 768-dim model leaves the old query_cache column in
        place and semantic cache writes start failing.

    Startup behavior:
      - query_cache.query_embedding:
        upgraded in place to the current model dimension when needed
      - semantic cache state in query_cache:
        cleared so stale semantic rows are rebuilt lazily on demand
      - search_index.embedding:
        if the persisted dimension is stale, rebuild all embeddings immediately
    """
    global _db_pool
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            qc_dim = _get_vector_dimension(cur, "query_cache", "query_embedding")
            si_dim = _get_vector_dimension(cur, "search_index", "embedding")

            if qc_dim is None:
                cur.execute(f"ALTER TABLE query_cache ADD COLUMN query_embedding vector({MODEL_EMBED_DIM})")
                qc_dim = MODEL_EMBED_DIM
                logger.info("Added missing query_cache.query_embedding column with %d dimensions", MODEL_EMBED_DIM)

            if qc_dim != MODEL_EMBED_DIM:
                logger.warning(
                    "query_cache.query_embedding dimension mismatch detected — db=%s model=%s; repairing schema",
                    qc_dim, MODEL_EMBED_DIM,
                )
                cur.execute("ALTER TABLE query_cache DROP COLUMN IF EXISTS query_embedding")
                cur.execute(f"ALTER TABLE query_cache ADD COLUMN query_embedding vector({MODEL_EMBED_DIM})")

            cur.execute(
                """
                UPDATE query_cache
                SET query_embedding        = NULL,
                    semantic_source_query  = NULL,
                    semantic_similarity    = NULL,
                    semantic_meta          = NULL,
                    semantic_cache_enabled = TRUE
                WHERE query_embedding       IS NOT NULL
                   OR semantic_source_query IS NOT NULL
                   OR semantic_similarity   IS NOT NULL
                   OR semantic_meta         IS NOT NULL
                """
            )
            cleared_semantic_rows = cur.rowcount

            if si_dim is None:
                raise RuntimeError("search_index.embedding column is missing")

            rebuild_count = 0
            if si_dim != MODEL_EMBED_DIM:
                logger.warning(
                    "search_index.embedding dimension mismatch detected — db=%s model=%s; rebuilding embeddings",
                    si_dim, MODEL_EMBED_DIM,
                )
                cur.execute("ALTER TABLE search_index DROP COLUMN IF EXISTS embedding")
                cur.execute(f"ALTER TABLE search_index ADD COLUMN embedding vector({MODEL_EMBED_DIM})")
                cur.execute("DROP INDEX IF EXISTS idx_search_embedding")
                cur.execute(
                    "CREATE INDEX idx_search_embedding ON search_index USING hnsw (embedding vector_cosine_ops)"
                )
                rebuild_count = _rebuild_search_index_embeddings(conn)

        logger.info(
            "Semantic cache reset completed — cleared_rows=%d search_index_rebuilt=%d",
            cleared_semantic_rows,
            rebuild_count,
        )


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
    _ensure_vector_schema_and_reset_semantic_cache()
    _start_invalidation_listener()
    _start_kafka_invalidation_consumer()
    _start_eureka_registration()
    yield
    # Shutdown: signal Eureka thread to deregister, then close pool
    _eureka_stop.set()
    if _db_pool:
        _db_pool.closeall()
        logger.info("Connection pool closed")

app = FastAPI(title="search-service", version="5.0.0", lifespan=lifespan)
if _tracing_enabled and _OTEL_AVAILABLE:
    FastAPIInstrumentor.instrument_app(app)

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

# Brand conflict detection — mutually exclusive brand mentions signal different intents.
_BRAND_TERMS = frozenset({
    # Sportswear
    "nike", "adidas", "puma", "reebok", "asics", "newbalance", "underarmour", "fila", "saucony",
    # Fashion / Apparel
    "zara", "hm", "gap", "levis", "gucci", "prada", "versace", "armani", "calvin", "tommy",
    # Electronics
    "apple", "samsung", "sony", "lg", "dell", "hp", "lenovo", "asus", "bose", "dyson",
    # General retail / footwear
    "vans", "converse", "timberland", "ugg", "crocs", "skechers",
})

# Category conflict detection — queries from different groups should never share a cache entry.
# Each inner frozenset is one mutually exclusive category group.
_CATEGORY_GROUPS: tuple = (
    frozenset({"shoes", "sneakers", "boots", "sandals", "loafers", "heels", "flats", "slippers", "mules"}),
    frozenset({"shorts", "pants", "trousers", "jeans", "leggings", "joggers", "chinos", "slacks"}),
    frozenset({"shirt", "shirts", "tshirt", "tee", "blouse", "polo", "hoodie", "sweatshirt", "tank"}),
    frozenset({"jacket", "coat", "parka", "blazer", "windbreaker", "vest", "cardigan"}),
    frozenset({"dress", "dresses", "skirt", "skirts", "gown", "romper", "jumpsuit"}),
    frozenset({"laptop", "laptops", "notebook", "macbook", "chromebook"}),
    frozenset({"phone", "phones", "smartphone", "iphone", "android", "mobile"}),
    frozenset({"headphones", "earbuds", "earphones", "airpods", "headset"}),
    frozenset({"watch", "watches", "smartwatch", "fitbit"}),
    frozenset({"bag", "bags", "backpack", "handbag", "purse", "tote", "satchel", "duffel"}),
)


def _tokenize(text: str) -> list:
    return [
        t for t in _TOKEN_SPLIT.split(text.lower())
        if t and len(t) > 1 and t not in _STOPWORDS
    ]


def _adaptive_soft_ttl(hit_count: int) -> int:
    """
    Python-side adaptive soft TTL. Used by _refresh_cache_entry()
    so background refreshes can set a warm initial soft window
    when hit_count is available from the DB before the upsert.

    Formula mirrors the PostgreSQL LOG() expression in _l2_get():
        L2_SOFT_TTL_SECONDS * (1 + log10(max(hit_count, 1)))
    Clamped to [L2_SOFT_TTL_SECONDS, ADAPTIVE_TTL_CEILING].

    Returns L2_SOFT_TTL_SECONDS unchanged if ADAPTIVE_TTL_ENABLED=False.

    Example outputs:
        hit_count=0    →  600s  (base; log10(1)=0 → multiplier=1.0)
        hit_count=10   → 1200s  (log10(10)=1.0   → multiplier=2.0)
        hit_count=100  → 1800s  (log10(100)=2.0  → multiplier=3.0)
        hit_count=1000 → 2400s  (log10(1000)=3.0 → multiplier=4.0)
    """
    if not ADAPTIVE_TTL_ENABLED:
        return L2_SOFT_TTL_SECONDS
    multiplier = 1.0 + math.log10(max(hit_count, 1))
    return int(min(L2_SOFT_TTL_SECONDS * multiplier, ADAPTIVE_TTL_CEILING))


def _has_price_intent_conflict(tokens_a: list, tokens_b: list) -> bool:
    set_a, set_b = set(tokens_a), set(tokens_b)
    a_budget  = bool(set_a & _BUDGET_TERMS)
    a_premium = bool(set_a & _PREMIUM_TERMS)
    b_budget  = bool(set_b & _BUDGET_TERMS)
    b_premium = bool(set_b & _PREMIUM_TERMS)
    return (a_budget and b_premium) or (a_premium and b_budget)


def _has_brand_conflict(tokens_a: list, tokens_b: list) -> bool:
    brands_a = set(tokens_a) & _BRAND_TERMS
    brands_b = set(tokens_b) & _BRAND_TERMS
    return bool(brands_a) and bool(brands_b) and brands_a != brands_b


def _has_category_conflict(tokens_a: list, tokens_b: list) -> bool:
    set_a, set_b = set(tokens_a), set(tokens_b)
    for group in _CATEGORY_GROUPS:
        a_in = bool(set_a & group)
        b_in = bool(set_b & group)
        if a_in != b_in:
            # one query is in this category group, the other is not —
            # check if the other falls in a different group
            other_set = set_b if a_in else set_a
            for other_group in _CATEGORY_GROUPS:
                if other_group is not group and bool(other_set & other_group):
                    return True
    return False


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
class _MetricsCounter:
    """Thread-safe counter map; safe under no-GIL Python (PEP 703)."""

    def __init__(self, initial: dict) -> None:
        self._lock = threading.Lock()
        self._data = dict(initial)

    def increment(self, key: str, n: int = 1) -> None:
        with self._lock:
            self._data[key] += n

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._data)

    def __getitem__(self, key: str):
        with self._lock:
            return self._data[key]


_metrics = _MetricsCounter({
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
    # Kafka invalidation counters (Phase 5)
    "kafka_events_received":     0,   # total messages consumed from product-updates
    "kafka_invalidations_ok":    0,   # events that successfully called _invalidate_product
    "kafka_events_skipped":      0,   # malformed events (missing 'id') or processing errors
    "cache_evictions_lru":       0,   # rows evicted by LRU pass in _l2_cleanup_expired
})

SEARCH_REQUESTS_TOTAL = Counter(
    "search_requests_total",
    "Total search requests by cache outcome.",
    ["cache_hit_source"],
)
SEARCH_REQUEST_LATENCY_SECONDS = Histogram(
    "search_request_latency_seconds",
    "End-to-end latency for the search endpoint.",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)


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


def _finalize_search_response(payload: dict, started_at: float) -> dict:
    SEARCH_REQUESTS_TOTAL.labels(
        cache_hit_source=payload.get("cache_hit_source", "UNKNOWN")
    ).inc()
    SEARCH_REQUEST_LATENCY_SECONDS.observe(time.monotonic() - started_at)
    return payload


class _SearchMetricsCollector:
    """Expose in-memory cache counters and derived cache values to Prometheus."""

    def collect(self):
        counters = CounterMetricFamily(
            "search_service_events_total",
            "Application counters exposed from the in-memory search metrics map.",
            labels=["metric"],
        )
        for key, value in _metrics.snapshot().items():
            counters.add_metric([key], value)
        yield counters

        stats = {}
        if _db_pool is not None:
            try:
                stats = cache_stats()
            except Exception:
                stats = {}
        gauges = GaugeMetricFamily(
            "search_service_values",
            "Derived and configuration values from the search-service cache subsystem.",
            labels=["metric"],
        )
        for key in (
            "l1_size_active",
            "l1_size_total",
            "l1_ttl_seconds",
            "l2_soft_ttl_seconds",
            "l2_hard_ttl_seconds",
            "query_cache_max_rows",
            "adaptive_ttl_enabled",
            "adaptive_ttl_ceiling_s",
            "lexical_near_threshold",
            "lexical_near_max_cands",
            "lexical_near_min_tokens",
            "semantic_strong_accept",
            "semantic_borderline_low",
            "semantic_max_candidates",
            "total_requests",
            "embedding_skips",
            "cache_hit_rate",
            "cold_entries",
            "warm_entries",
            "hot_entries",
            "viral_entries",
            "avg_soft_ttl_remaining_s",
            "max_hit_count",
        ):
            value = stats.get(key)
            if value is not None:
                gauges.add_metric([key], float(value))
        yield gauges



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
                    SET    hit_count       = hit_count + 1,
                           last_hit_at    = now(),
                           soft_expires_at = CASE
                               WHEN %s THEN
                                   -- Adaptive: extend window using log10(new hit_count).
                                   -- GREATEST: never shorten an expiry already further out.
                                   -- LEAST:    never let soft exceed hard.
                                   LEAST(
                                       hard_expires_at,
                                       GREATEST(
                                           soft_expires_at,
                                           now() + make_interval(secs =>
                                               LEAST(
                                                   %s::float * (1.0 + LOG(GREATEST(hit_count + 1, 1))),
                                                   %s::float
                                               )
                                           )
                                       )
                                   )
                               ELSE
                                   soft_expires_at
                           END
                    WHERE  query_hash        = %s
                      AND  filter_hash       = %s
                      AND  sort_key          = %s
                      AND  page_number       = %s
                      AND  page_limit        = %s
                      AND  hard_expires_at   > now()
                      AND  freshness_status != 'HARD_EXPIRED'
                    RETURNING ordered_product_ids, result_count, response_meta,
                              freshness_status, soft_expires_at, hard_expires_at,
                              hit_count
                    """,
                    (
                        ADAPTIVE_TTL_ENABLED,           # %s 1 — CASE WHEN condition
                        float(L2_SOFT_TTL_SECONDS),     # %s 2 — base seconds for LOG
                        float(ADAPTIVE_TTL_CEILING),    # %s 3 — LEAST cap (= hard TTL)
                        query_hash,                     # %s 4
                        filter_hash,                    # %s 5
                        sort_key,                       # %s 6
                        page_number,                    # %s 7
                        page_limit,                     # %s 8
                    ),
                )
                row = cur.fetchone()
        if row is None:
            return None
        eff     = _effective_freshness(row["freshness_status"], row["soft_expires_at"])
        hard_dt = row["hard_expires_at"]
        if hard_dt and hard_dt.tzinfo is None:
            hard_dt = hard_dt.replace(tzinfo=timezone.utc)
        logger.debug(
            "L2 hit — hash=%.8s… hit_count=%d soft_expires_at=%s freshness=%s",
            query_hash, row["hit_count"], row["soft_expires_at"], eff,
        )
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
    # NOTE: _l2_put always writes the base soft TTL regardless of
    # ADAPTIVE_TTL_ENABLED. The adaptive extension happens live in
    # _l2_get() on each subsequent hit. Do not call _adaptive_soft_ttl()
    # here — hit_count is unknown at insert time and resets to 0 on
    # conflict, so the base window is always the correct starting point.
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
        _metrics.increment("writes")
    except psycopg2.Error as exc:
        logger.warning("L2 cache write error (non-fatal): %s", exc)


def _l2_cleanup_expired() -> None:
    """
    Lazily delete rows that have been hard-expired for more than 24 hours,
    then evict the least-recently-accessed rows if the table exceeds
    QUERY_CACHE_MAX_ROWS. Called opportunistically on each cache write.
    """
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM query_cache WHERE hard_expires_at < now() - interval '24 hours'"
                )
    except psycopg2.Error as exc:
        logger.debug("L2 cleanup error (non-fatal): %s", exc)

    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM query_cache")
                (total,) = cur.fetchone()
                excess = total - QUERY_CACHE_MAX_ROWS
                if excess > 0:
                    cur.execute(
                        """
                        DELETE FROM query_cache
                        WHERE cache_id IN (
                            SELECT cache_id FROM query_cache
                            ORDER BY COALESCE(last_hit_at, created_at) ASC
                            LIMIT %s
                        )
                        """,
                        (excess,),
                    )
                    _metrics.increment("cache_evictions_lru", excess)
                    logger.info("LRU eviction removed %d rows from query_cache", excess)
    except psycopg2.Error as exc:
        logger.debug("L2 LRU eviction error (non-fatal): %s", exc)


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

        _metrics.increment("invalidation_events")
        _metrics.increment("invalidated_rows",          updated)
        _metrics.increment("l1_evictions_from_notify",  l1_evicted)

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
    _metrics.increment("refresh_triggers")
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

        _metrics.increment("refresh_successes")
        logger.info(
            "Background refresh OK — normalized=%r results=%d",
            normalized, result_count,
        )
    except Exception as exc:
        _metrics.increment("refresh_failures")
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
            _metrics.increment("l1_evictions_from_notify", evicted)
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


def _start_invalidation_listener_thread() -> None:
    t = threading.Thread(
        target=_invalidation_listener_loop,
        daemon=True,
        name="invalidation-listener",
    )
    t.start()
    logger.info("Invalidation listener thread started")

# Public alias preserving the original callable name.
_start_invalidation_listener = _start_invalidation_listener_thread


# ---------------------------------------------------------------------------
# Phase 5 — Kafka invalidation consumer (closes the Kafka → cache gap)
# ---------------------------------------------------------------------------
def _kafka_invalidation_consumer_loop() -> None:
    """
    Daemon thread: consumes from 'product-updates' and calls _invalidate_product()
    for every event, mirroring the invalidation that ingestion-worker triggers on
    search_index so that query_cache entries are marked stale within seconds rather
    than waiting for the hard TTL (60 min).

    Offset reset policy: 'latest'
      On restart we skip events published during the downtime window. This is the
      right trade-off because:
        - Replaying old events triggers unnecessary invalidations on an already-fresh
          or already-hard-expired cache (no benefit).
        - The worst-case staleness equals the hard TTL (60 min), which is the
          pre-feature baseline — we never make things worse than before this feature.
        - On first boot the cache is empty, so there is nothing to invalidate anyway.

    Consumer group: KAFKA_GROUP_ID (distinct from the ingestion-worker group) so both
    consumers receive every message independently and do not compete for partition assignments.

    Resilience:
      - NoBrokersAvailable on startup: logged and retried with exponential backoff.
      - Any per-event exception: logged and skipped (consumer loop continues).
      - Any consumer-level exception: logged, consumer closed, backoff, reconnect.
      - _invalidate_product() checks out and returns pool connections internally;
        no pool connection is held while blocked waiting for Kafka messages.
    """
    backoff = 5  # initial retry delay in seconds
    while True:
        consumer = None
        try:
            consumer = KafkaConsumer(
                KAFKA_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP,
                group_id=KAFKA_GROUP_ID,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                auto_offset_reset="latest",
                enable_auto_commit=True,
                session_timeout_ms=30_000,
                heartbeat_interval_ms=10_000,
            )
            logger.info(
                "Kafka invalidation consumer connected — topic=%s group=%s broker=%s",
                KAFKA_TOPIC, KAFKA_GROUP_ID, KAFKA_BOOTSTRAP,
            )
            backoff = 5  # reset backoff on successful connection
            for message in consumer:
                try:
                    event = message.value
                    _metrics.increment("kafka_events_received")

                    # Event field: 'id' — matches ingestion-worker producer contract.
                    # Using wrong field name here causes silent skip on every event.
                    product_id = event.get("id")
                    if not product_id:
                        _metrics.increment("kafka_events_skipped")
                        logger.debug(
                            "Kafka event skipped — missing 'id' field, keys=%s",
                            list(event.keys()) if isinstance(event, dict) else type(event),
                        )
                        continue

                    event_type     = (event.get("eventType") or "FULL_UPDATE").upper()
                    # changedFields is not produced by ingestion-worker today; included
                    # for forward-compatibility if the event contract is extended.
                    changed_fields = event.get("changedFields")

                    _invalidate_product(product_id, event_type, changed_fields)
                    _metrics.increment("kafka_invalidations_ok")
                    logger.debug(
                        "Kafka invalidation OK — product_id=%r event_type=%s",
                        product_id, event_type,
                    )

                except Exception as exc:
                    _metrics.increment("kafka_events_skipped")
                    logger.warning(
                        "Kafka event processing error (event skipped): %s", exc,
                    )

        except NoBrokersAvailable:
            logger.warning(
                "Kafka not available — retrying in %ds (broker=%s)",
                backoff, KAFKA_BOOTSTRAP,
            )
        except Exception as exc:
            logger.warning(
                "Kafka invalidation consumer error — retrying in %ds: %s", backoff, exc,
            )
        finally:
            if consumer is not None:
                try:
                    consumer.close()
                except Exception:
                    pass

        time.sleep(backoff)
        backoff = min(backoff * 2, 120)  # exponential backoff, cap at 2 min


def _start_kafka_invalidation_consumer() -> None:
    t = threading.Thread(
        target=_kafka_invalidation_consumer_loop,
        daemon=True,
        name="kafka-invalidation-consumer",
    )
    t.start()
    logger.info("Kafka invalidation consumer thread started — topic=%s", KAFKA_TOPIC)


# ---------------------------------------------------------------------------
# Eureka registration — daemon thread registers, heartbeats, and deregisters
# ---------------------------------------------------------------------------
_eureka_stop = threading.Event()


def _eureka_registration_loop() -> None:
    """
    Daemon thread: registers this instance with Eureka on startup, sends a
    heartbeat PUT every EUREKA_HEARTBEAT_S seconds, and handles unavailability
    with exponential backoff. The main request path is never blocked — if Eureka
    is down the gateway falls back to its hardcoded URI.
    """
    registration_payload = json.dumps({
        "instance": {
            "instanceId":       EUREKA_INSTANCE_ID,
            "hostName":         EUREKA_INSTANCE_HOST,
            "app":              EUREKA_APP_NAME,
            "ipAddr":           EUREKA_INSTANCE_HOST,
            "status":           "UP",
            "overriddenStatus": "UNKNOWN",
            "port":             {"$": EUREKA_PORT, "@enabled": "true"},
            "securePort":       {"$": 443,         "@enabled": "false"},
            "healthCheckUrl":   f"http://{EUREKA_INSTANCE_HOST}:{EUREKA_PORT}/health",
            "statusPageUrl":    f"http://{EUREKA_INSTANCE_HOST}:{EUREKA_PORT}/health",
            "homePageUrl":      f"http://{EUREKA_INSTANCE_HOST}:{EUREKA_PORT}/",
            "dataCenterInfo":   {
                "@class": "com.netflix.appinfo.InstanceInfo$DefaultDataCenterInfo",
                "name":   "MyOwn",
            },
            "leaseInfo": {
                "renewalIntervalInSecs": EUREKA_HEARTBEAT_S,
                "durationInSecs":        EUREKA_LEASE_S,
            },
            "metadata": {"management.port": str(EUREKA_PORT)},
            "vipAddress":       EUREKA_APP_NAME,
            "secureVipAddress": EUREKA_APP_NAME,
            "isCoordinatingDiscoveryServer": "false",
        }
    }).encode()

    register_url   = f"{EUREKA_URI.rstrip('/')}/apps/{EUREKA_APP_NAME}"
    heartbeat_url  = f"{register_url}/{EUREKA_INSTANCE_ID}"
    registered     = False
    backoff        = 5  # initial retry delay in seconds

    while not _eureka_stop.is_set():
        try:
            if not registered:
                req = urllib.request.Request(
                    register_url,
                    data=registration_payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status in (200, 204):
                        registered = True
                        backoff    = 5
                        logger.info(
                            "Registered with Eureka — app=%s instanceId=%s",
                            EUREKA_APP_NAME, EUREKA_INSTANCE_ID,
                        )
            else:
                req = urllib.request.Request(heartbeat_url, method="PUT")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 404:
                        # Eureka lost our registration (restart/eviction); re-register.
                        registered = False
                        logger.warning("Eureka heartbeat 404 — re-registering")
                        continue

        except urllib.error.HTTPError as exc:
            if exc.code == 404 and registered:
                registered = False
                logger.warning("Eureka heartbeat 404 — re-registering")
                continue
            logger.debug("Eureka %s error (non-fatal): %s",
                         "registration" if not registered else "heartbeat", exc)
            if not registered:
                _eureka_stop.wait(backoff)
                backoff = min(backoff * 2, 120)
                continue
        except Exception as exc:
            logger.debug("Eureka %s error (non-fatal): %s",
                         "registration" if not registered else "heartbeat", exc)
            if not registered:
                _eureka_stop.wait(backoff)
                backoff = min(backoff * 2, 120)
                continue

        _eureka_stop.wait(EUREKA_HEARTBEAT_S)

    # Graceful deregistration on shutdown.
    try:
        req = urllib.request.Request(heartbeat_url, method="DELETE")
        urllib.request.urlopen(req, timeout=5)
        logger.info("Deregistered from Eureka — instanceId=%s", EUREKA_INSTANCE_ID)
    except Exception as exc:
        logger.debug("Eureka deregistration error (non-fatal): %s", exc)


def _start_eureka_registration() -> None:
    t = threading.Thread(
        target=_eureka_registration_loop,
        daemon=True,
        name="eureka-registration",
    )
    t.start()
    logger.info("Eureka registration thread started — app=%s uri=%s", EUREKA_APP_NAME, EUREKA_URI)


# LISTEN/NOTIFY daemon, Kafka consumer, and Eureka registration are started inside lifespan() above.


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

    if len(candidate_normalized) < MIN_CACHEABLE_QUERY_CHARS:
        stats["reject_reason"] = "candidate_too_short"
        return False, stats

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

    if _has_brand_conflict(incoming_tokens, candidate_tokens):
        stats["reject_reason"] = "brand_conflict"
        return False, stats

    if _has_category_conflict(incoming_tokens, candidate_tokens):
        stats["reject_reason"] = "category_conflict"
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
        return _finalize_search_response(
            {"query": q, "total": 0, "results": [], "cache_hit_source": "EMPTY"},
            t_start,
        )

    # ── Step 2b: Cache eligibility ───────────────────────────────────────────
    # Very short queries (e.g. "c", "ab") produce near-meaningless embeddings
    # that pollute the semantic candidate pool. Skip ALL cache tiers and go
    # straight to hybrid search; do not write results back to the cache.
    _cacheable = len(normalized) >= MIN_CACHEABLE_QUERY_CHARS

    # ── Step 3: L1 in-process cache ──────────────────────────────────────────
    if not _cacheable:
        l1_entry = None
    with _start_span("cache.l1.lookup") as _sp:
        l1_entry = _l1_get(query_hash)
        _sp.set_attribute("cache.hit", l1_entry is not None)
        if l1_entry is not None:
            _sp.set_attribute("cache.freshness", l1_entry.freshness_status)
    if l1_entry is not None:
        _metrics.increment("l1_hits")
        eff = l1_entry.freshness_status     # ACTIVE or SOFT_EXPIRED (HARD_EXPIRED evicted)
        if eff == "SOFT_EXPIRED":
            _metrics.increment("soft_expired_cache_hits")
            background_tasks.add_task(
                _refresh_cache_entry,
                normalized, query_hash, filter_hash, sort_key,
                page_number, page_limit, incoming_tokens,
            )
        else:
            _metrics.increment("active_cache_hits")

        with _start_span("search.hydrate") as _sp:
            docs = _hydrate(l1_entry.ordered_product_ids)
            _sp.set_attribute("hydrate.product_count", len(docs))
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "Cache L1 HIT — normalized=%r hash=%.8s… freshness=%s results=%d latency_ms=%d",
            normalized, query_hash, eff, len(docs), elapsed_ms,
        )
        return _finalize_search_response({
            "query": q, "total": len(docs), "results": docs,
            "cache_hit_source": "L1", "freshness_status": eff,
        }, t_start)

    # ── Step 4: L2 Postgres exact cache ──────────────────────────────────────
    if not _cacheable:
        l2_result = None
    with _start_span("cache.l2.lookup") as _sp:
        l2_result = _l2_get(query_hash, filter_hash, sort_key, page_number, page_limit)
        _sp.set_attribute("cache.hit", l2_result is not None)
        if l2_result is not None:
            _sp.set_attribute("cache.freshness", l2_result.freshness_status)
    if l2_result is not None:
        eff = l2_result.freshness_status    # ACTIVE or SOFT_EXPIRED
        if eff == "SOFT_EXPIRED":
            _metrics.increment("soft_expired_cache_hits")
            background_tasks.add_task(
                _refresh_cache_entry,
                normalized, query_hash, filter_hash, sort_key,
                page_number, page_limit, incoming_tokens,
            )
        else:
            _metrics.increment("active_cache_hits")
        _metrics.increment("l2_hits")

        with _start_span("search.hydrate") as _sp:
            docs = _hydrate(l2_result.ordered_product_ids)
            _sp.set_attribute("hydrate.product_count", len(docs))
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
        return _finalize_search_response({
            "query": q, "total": len(docs), "results": docs,
            "cache_hit_source": "L2", "freshness_status": eff,
        }, t_start)

    # ── Step 5: Lexical-near cache lookup ────────────────────────────────────
    if not _cacheable:
        candidates = []
    with _start_span("cache.lexical_near.lookup") as _lex_sp:
        candidates = _lexical_near_get(
            normalized, filter_hash, sort_key, page_number, page_limit
        )
        _lex_sp.set_attribute("cache.candidates_evaluated", len(candidates))
        _lex_sp.set_attribute("cache.hit", False)
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
                _metrics.increment("hard_expired_rejects")
                continue

            accepted, accept_stats = _accept_lexical_near_candidate(incoming_tokens, candidate)
            if not accepted:
                _metrics.increment("lexical_near_rejects")
                logger.info(
                    "Lexical-near REJECT — normalized=%r candidate=%r "
                    "trgm_score=%.4f reason=%s",
                    normalized,
                    candidate["normalized_query"],
                    accept_stats.get("trgm_score", 0.0),
                    accept_stats.get("reject_reason", "unknown"),
                )
                continue

            _metrics.increment("lexical_near_hits")
            if cand_eff == "SOFT_EXPIRED":
                _metrics.increment("soft_expired_cache_hits")
            else:
                _metrics.increment("active_cache_hits")

            ordered_ids  = list(candidate["ordered_product_ids"])
            with _start_span("search.hydrate") as _sp:
                docs = _hydrate(ordered_ids)
                _sp.set_attribute("hydrate.product_count", len(docs))
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
            _lex_sp.set_attribute("cache.hit", True)
            return _finalize_search_response({
                "query": q, "total": len(docs), "results": docs,
                "cache_hit_source": "LEXICAL_NEAR", "freshness_status": "ACTIVE",
            }, t_start)

    # ── Step 6: Compute embedding (once; shared for semantic + hybrid) ────────
    try:
        with _start_span("embedding.compute") as _sp:
            _sp.set_attribute("embedding.model", EMBED_MODEL)
            _sp.set_attribute("embedding.query", normalized)
            t_embed   = time.monotonic()
            embedding = model.encode(normalized).tolist()
            vec_str   = _vec_str(embedding)
            embed_ms  = int((time.monotonic() - t_embed) * 1000)
        _metrics.increment("embeddings_computed")
    except Exception as exc:
        logger.error("Embedding computation failed: %s", exc)
        raise HTTPException(status_code=503, detail="Embedding service unavailable")

    # ── Step 6 (cont): Semantic cache lookup ─────────────────────────────────
    if not _cacheable:
        sem_candidates = []
    with _start_span("cache.semantic.lookup") as _sem_sp:
        t_sem_lookup   = time.monotonic()
        sem_candidates = _semantic_get(vec_str, filter_hash, sort_key, page_number, page_limit)
        sem_lookup_ms  = int((time.monotonic() - t_sem_lookup) * 1000)
        _sem_sp.set_attribute("cache.candidates_evaluated", len(sem_candidates))
        _sem_sp.set_attribute("cache.hit", False)

        logger.info(
            "Semantic candidates — normalized=%r count=%d lookup_ms=%d",
            normalized, len(sem_candidates), sem_lookup_ms,
        )

        for sem_candidate in sem_candidates:
            _metrics.increment("semantic_candidates_seen")

            # Phase 4: compute effective freshness of this semantic candidate
            cand_eff = _effective_freshness(
                sem_candidate.get("freshness_status", "ACTIVE"),
                sem_candidate.get("soft_expires_at"),
            )
            if cand_eff == "HARD_EXPIRED":
                _metrics.increment("hard_expired_rejects")
                continue

            accepted, sem_stats = _accept_semantic_candidate(incoming_tokens, sem_candidate)
            if not accepted:
                _metrics.increment("semantic_rejects")
                logger.info(
                    "Semantic REJECT — normalized=%r candidate=%r semantic_similarity=%.4f reason=%s",
                    normalized,
                    sem_candidate["normalized_query"],
                    sem_stats.get("similarity", 0.0),
                    sem_stats.get("reject_reason", "unknown"),
                )
                continue

            _metrics.increment("semantic_hits")
            if cand_eff == "SOFT_EXPIRED":
                _metrics.increment("soft_expired_cache_hits")
            else:
                _metrics.increment("active_cache_hits")

            ordered_ids = list(sem_candidate["ordered_product_ids"])
            with _start_span("search.hydrate") as _sp:
                docs = _hydrate(ordered_ids)
                _sp.set_attribute("hydrate.product_count", len(docs))

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
                "Cache SEMANTIC HIT — normalized=%r source=%r semantic_similarity=%.4f "
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
            _sem_sp.set_attribute("cache.hit", True)
            return _finalize_search_response({
                "query": q, "total": len(docs), "results": docs,
                "cache_hit_source": "SEMANTIC", "freshness_status": "ACTIVE",
            }, t_start)

    # ── Step 7: Cache miss — run full hybrid search ───────────────────────────
    with _start_span("search.hybrid") as _hyb_sp:
        _metrics.increment("misses")
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
            _hyb_sp.set_attribute("search.results_count", result_count)

            response_meta = {
                "cache_version": 5,
                "search_mode":   "hybrid",
                "embed_ms":      embed_ms,
                "search_ms":     search_ms,
            }

            now_utc     = datetime.now(timezone.utc)
            hard_exp_dt = now_utc + timedelta(seconds=L2_HARD_TTL_SECONDS)

            if _cacheable:
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
            return _finalize_search_response({
                "query":            q,
                "total":            result_count,
                "results":          docs,
                "cache_hit_source": "MISS",
                "freshness_status": "ACTIVE",
            }, t_start)

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
    """Diagnostics: cache hit/miss counters, L1 occupancy, Phase 2/3/4/5 metrics."""
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

    # ── Phase 5: adaptive TTL temperature histogram ──────────────────────────
    # Non-fatal — a DB error here must never crash the stats endpoint.
    ttl_histogram = {
        "cold_entries":             0,    # hit_count = 0 (never hit since write)
        "warm_entries":             0,    # hit_count 1–9
        "hot_entries":              0,    # hit_count 10–99
        "viral_entries":            0,    # hit_count >= 100
        "avg_soft_ttl_remaining_s": None, # None when table is empty
        "max_hit_count":            0,
    }
    try:
        with get_db_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE hit_count = 0)               AS cold_entries,
                        COUNT(*) FILTER (WHERE hit_count BETWEEN 1 AND 9)   AS warm_entries,
                        COUNT(*) FILTER (WHERE hit_count BETWEEN 10 AND 99) AS hot_entries,
                        COUNT(*) FILTER (WHERE hit_count >= 100)            AS viral_entries,
                        ROUND(AVG(
                            EXTRACT(EPOCH FROM (soft_expires_at - now()))
                        ))::int                                             AS avg_soft_ttl_remaining_s,
                        MAX(hit_count)                                      AS max_hit_count
                    FROM query_cache
                    WHERE hard_expires_at  > now()
                      AND freshness_status != 'HARD_EXPIRED'
                    """
                )
                row = cur.fetchone()
        if row:
            ttl_histogram = {
                k: (int(v) if v is not None else None)
                for k, v in dict(row).items()
            }
    except psycopg2.Error as exc:
        logger.debug("TTL histogram fetch error (non-fatal): %s", exc)

    return {
        # L1
        "l1_size_active":              l1_active,
        "l1_size_total":               len(_l1_cache),
        "l1_ttl_seconds":              L1_TTL_SECONDS,
        # L2 TTLs (Phase 4)
        "l2_soft_ttl_seconds":         L2_SOFT_TTL_SECONDS,
        "l2_hard_ttl_seconds":         L2_HARD_TTL_SECONDS,
        "query_cache_max_rows":        QUERY_CACHE_MAX_ROWS,
        # Adaptive TTL config (Phase 5)
        "adaptive_ttl_enabled":        ADAPTIVE_TTL_ENABLED,
        "adaptive_ttl_ceiling_s":      ADAPTIVE_TTL_CEILING,
        # Lexical-near config (Phase 2)
        "lexical_near_threshold":      LEXICAL_NEAR_SIMILARITY_THRESHOLD,
        "lexical_near_max_cands":      LEXICAL_NEAR_MAX_CANDIDATES,
        "lexical_near_min_tokens":     LEXICAL_NEAR_MIN_SHARED_TOKENS,
        # Semantic config (Phase 3)
        "semantic_strong_accept":      SEMANTIC_STRONG_ACCEPT,
        "semantic_borderline_low":     SEMANTIC_BORDERLINE_LOW,
        "semantic_max_candidates":     SEMANTIC_MAX_CANDIDATES,
        # All counters
        **_metrics.snapshot(),
        # Derived
        "total_requests":              total_requests,
        "embedding_skips":             _metrics["lexical_near_hits"],
        "cache_hit_rate":              round(total_cache_hits / max(total_requests, 1), 4),
        # Adaptive TTL histogram (Phase 5)
        **ttl_histogram,
    }


REGISTRY.register(_SearchMetricsCollector())


@app.get("/metrics")
def metrics():
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
