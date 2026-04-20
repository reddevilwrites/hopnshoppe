"""
ingestion-worker — Semantic Search Pipeline (pgvector)
=======================================================
Consumes product-update events from Kafka, generates sentence embeddings,
and upserts rows into the search_index table in PostgreSQL (pgvector).

Event types
-----------
  FULL_UPDATE   — full product data; rebuilds the denormalized_doc and embedding.
                  This is the default when 'eventType' is absent (backward-compat
                  with the catalog-service which publishes plain UnifiedProductDTO).
  PRICE_UPDATE  — price/stock fields only; skips embedding regeneration.

Topic layout
------------
  product-updates      — main ingest topic (produced by catalog-service)
  product-updates.DLQ  — dead letter queue (failed DB writes after retries)

Kafka event contract
--------------------
FULL_UPDATE (all fields):
  {
    "eventType":   "FULL_UPDATE",   // optional — absent events default to FULL_UPDATE
    "id":          "sku-123",
    "name":        "Running Shoe",
    "description": "<p>HTML or plain text</p>",
    "price":       4999.00,
    "imageUrl":    "https://...",
    "source":      "AEM" | "MARKETPLACE",
    "brand":       "Acme",          // optional
    "currency":    "USD",           // optional, defaults to USD
    "inStock":     true             // optional, defaults to true
  }

PRICE_UPDATE (required fields only):
  {
    "eventType": "PRICE_UPDATE",
    "id":        "sku-123",
    "price":     5499.00,
    "currency":  "USD",             // optional, defaults to USD
    "inStock":   true               // optional, defaults to true
  }
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from bs4 import BeautifulSoup
from kafka import KafkaConsumer, KafkaProducer
from prometheus_client import Counter, Gauge, start_http_server
from sentence_transformers import SentenceTransformer

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
    from opentelemetry.instrumentation.kafka import KafkaInstrumentor
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
    """Emit JSON logs with trace/span correlation when available."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": "ingestion-worker",
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
logger = logging.getLogger("ingestion-worker")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP    = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
TOPIC              = "product-updates"
DLQ_TOPIC          = "product-updates.DLQ"

SEARCH_DB_HOST     = os.environ.get("SEARCH_DB_HOST", "search-db")
SEARCH_DB_PORT     = int(os.environ.get("SEARCH_DB_PORT", "5432"))
SEARCH_DB_NAME     = os.environ.get("SEARCH_DB_NAME", "search_db")
SEARCH_DB_USER     = os.environ.get("SEARCH_DB_USER", "postgres")
SEARCH_DB_PASSWORD = os.environ["SEARCH_DB_PASSWORD"]

EMBED_MODEL        = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
KAFKA_READY_WAIT   = 15                    # seconds before starting consumer
METRICS_PORT       = int(os.environ.get("METRICS_PORT", "9108"))

INGESTION_EVENTS_TOTAL = Counter(
    "ingestion_worker_events_total",
    "Kafka events processed by event type and outcome.",
    ["event_type", "outcome"],
)
INGESTION_DB_CONNECTED = Gauge(
    "ingestion_worker_db_connected",
    "Whether ingestion-worker currently has an open database connection.",
)

# ---------------------------------------------------------------------------
# Distributed tracing — initialised before DB connection and Kafka consumer
# ---------------------------------------------------------------------------
def _init_tracing() -> None:
    """
    Set up OpenTelemetry tracing with psycopg2 and Kafka auto-instrumentation.
    A missing endpoint or ImportError is non-fatal — the worker continues normally.
    """
    if not _OTEL_AVAILABLE:
        logger.info("OTel packages not installed — tracing disabled")
        return
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set — tracing disabled")
        return
    try:
        service_name = os.environ.get("OTEL_SERVICE_NAME", "ingestion-worker")
        resource     = Resource({"service.name": service_name})
        provider     = TracerProvider(resource=resource)
        exporter     = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        Psycopg2Instrumentor().instrument()
        KafkaInstrumentor().instrument()
        logger.info("OTel tracing enabled — endpoint=%s service=%s", endpoint, service_name)
    except Exception as exc:
        logger.warning("OTel tracing init failed (non-fatal): %s", exc)


_init_tracing()

# ---------------------------------------------------------------------------
# Startup — load model and connect to search-db (with retry)
# ---------------------------------------------------------------------------
logger.info("Loading embedding model '%s' …", EMBED_MODEL)
model = SentenceTransformer(EMBED_MODEL)
MODEL_EMBED_DIM = int(model.get_sentence_embedding_dimension())
logger.info("Embedding model dimension resolved to %d", MODEL_EMBED_DIM)


def _get_vector_dimension(
    conn: psycopg2.extensions.connection,
    table_name: str,
    column_name: str,
) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.atttypmod
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = %s
              AND a.attname = %s
              AND a.attnum > 0
              AND NOT a.attisdropped
            """,
            (table_name, column_name),
        )
        row = cur.fetchone()
    if row is None:
        return None
    dim = row[0]
    return int(dim) if dim and dim > 0 else None


def _validate_embedding_schema(conn: psycopg2.extensions.connection) -> None:
    db_dim = _get_vector_dimension(conn, "search_index", "embedding")
    if db_dim is None:
        raise RuntimeError("search_index.embedding column is missing")
    if db_dim != MODEL_EMBED_DIM:
        raise RuntimeError(
            f"search_index.embedding dimension mismatch: db={db_dim} model={MODEL_EMBED_DIM}"
        )
    logger.info("search_index.embedding dimension verified — db=%d model=%d", db_dim, MODEL_EMBED_DIM)


def _connect_db() -> psycopg2.extensions.connection:
    dsn = (
        f"host={SEARCH_DB_HOST} port={SEARCH_DB_PORT} "
        f"dbname={SEARCH_DB_NAME} user={SEARCH_DB_USER} "
        f"password={SEARCH_DB_PASSWORD}"
    )
    for attempt in range(1, 11):
        try:
            conn = psycopg2.connect(dsn)
            conn.autocommit = False
            _validate_embedding_schema(conn)
            logger.info("Connected to search-db on attempt %d", attempt)
            INGESTION_DB_CONNECTED.set(1)
            return conn
        except psycopg2.OperationalError as exc:
            logger.warning("DB connect attempt %d/10 failed: %s", attempt, exc)
            time.sleep(min(2 ** (attempt - 1), 30))
    raise RuntimeError("Could not connect to search-db after 10 attempts")


conn = _connect_db()

producer = KafkaProducer(
    bootstrap_servers=KAFKA_BOOTSTRAP,
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
)

# ---------------------------------------------------------------------------
# Text preprocessing helpers
# ---------------------------------------------------------------------------
def strip_html(text: str) -> str:
    """Remove all HTML tags; return plain text."""
    return BeautifulSoup(text or "", "html.parser").get_text(separator=" ")


def normalize(text: str) -> str:
    """Lowercase and collapse whitespace."""
    return " ".join(text.lower().split())


def _format_price(amount: float, currency: str = "USD") -> str:
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{amount:,.2f}"


# ---------------------------------------------------------------------------
# Build the denormalized search-result document
# Includes only fields needed to render a product card — no PDP fields.
# ---------------------------------------------------------------------------
def _build_denormalized_doc(event: dict) -> dict:
    product_id = str(event.get("id", ""))
    name       = event.get("name") or ""
    desc_raw   = event.get("description") or ""
    price      = float(event.get("price") or 0.0)
    image_url  = event.get("imageUrl") or ""
    source     = event.get("source") or "UNKNOWN"
    brand      = event.get("brand") or None
    currency   = event.get("currency") or "USD"
    in_stock   = bool(event.get("inStock", True))

    short_desc  = normalize(strip_html(desc_raw))[:300]
    badge_label = "Marketplace" if source == "MARKETPLACE" else "AEM Store"

    return {
        "id":               product_id,
        "slug":             f"/products/{product_id}",
        "title":            name,
        "brand":            brand,
        "shortDescription": short_desc,
        "image":            {"url": image_url},
        "price": {
            "amount":    price,
            "currency":  currency,
            "formatted": _format_price(price, currency),
        },
        "badges":  [badge_label],
        "inStock": in_stock,
    }


# ---------------------------------------------------------------------------
# DB upsert helpers
# ---------------------------------------------------------------------------
_FULL_UPSERT_SQL = """
INSERT INTO search_index
    (product_id, title, brand, search_text, denormalized_doc,
     embedding, price_amount, currency, in_stock, updated_at)
VALUES
    (%(product_id)s, %(title)s, %(brand)s, %(search_text)s,
     %(denormalized_doc)s::jsonb, %(embedding)s::vector,
     %(price_amount)s, %(currency)s, %(in_stock)s, now())
ON CONFLICT (product_id) DO UPDATE SET
    title            = EXCLUDED.title,
    brand            = EXCLUDED.brand,
    search_text      = EXCLUDED.search_text,
    denormalized_doc = EXCLUDED.denormalized_doc,
    embedding        = EXCLUDED.embedding,
    price_amount     = EXCLUDED.price_amount,
    currency         = EXCLUDED.currency,
    in_stock         = EXCLUDED.in_stock,
    updated_at       = now()
"""

# Uses jsonb_set to update only the price sub-fields without touching other
# denormalized_doc keys (e.g. title, image) that weren't part of the event.
_PRICE_UPDATE_SQL = """
UPDATE search_index
SET
    price_amount     = %(price_amount)s,
    currency         = %(currency)s,
    in_stock         = %(in_stock)s,
    denormalized_doc = jsonb_set(
                         jsonb_set(
                           jsonb_set(
                             denormalized_doc,
                             '{price,amount}',    %(price_amount_json)s::jsonb
                           ),
                           '{price,currency}',  %(currency_json)s::jsonb
                         ),
                         '{price,formatted}',   %(price_formatted_json)s::jsonb
                       ),
    updated_at       = now()
WHERE product_id = %(product_id)s
"""


def _vec_str(embedding: list) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


def _upsert_full(event: dict, doc: dict) -> None:
    product_id  = str(event.get("id", ""))
    name        = event.get("name") or ""
    brand       = event.get("brand") or None
    desc_plain  = normalize(strip_html(event.get("description") or ""))
    price       = float(event.get("price") or 0.0)
    currency    = event.get("currency") or "USD"
    in_stock    = bool(event.get("inStock", True))
    source      = event.get("source") or "UNKNOWN"

    # Concatenate all searchable text fields for the FTS index
    search_text = " ".join(filter(None, [name, desc_plain, brand, source]))

    text_to_embed = f"{name}. {desc_plain}".strip()
    embedding     = model.encode(text_to_embed).tolist()

    with conn.cursor() as cur:
        cur.execute(_FULL_UPSERT_SQL, {
            "product_id":      product_id,
            "title":           name,
            "brand":           brand,
            "search_text":     search_text,
            "denormalized_doc": json.dumps(doc),
            "embedding":       _vec_str(embedding),
            "price_amount":    price,
            "currency":        currency,
            "in_stock":        in_stock,
        })
    conn.commit()
    logger.info("FULL_UPDATE upserted product '%s'", product_id)


def _update_price(event: dict) -> None:
    product_id = str(event.get("id", ""))
    price      = float(event.get("price") or 0.0)
    currency   = event.get("currency") or "USD"
    in_stock   = bool(event.get("inStock", True))

    with conn.cursor() as cur:
        cur.execute(_PRICE_UPDATE_SQL, {
            "product_id":           product_id,
            "price_amount":         price,
            "currency":             currency,
            "in_stock":             in_stock,
            "price_amount_json":    json.dumps(price),
            "currency_json":        json.dumps(currency),
            "price_formatted_json": json.dumps(_format_price(price, currency)),
        })
        if cur.rowcount == 0:
            logger.warning(
                "PRICE_UPDATE for unknown product '%s' — no row updated", product_id
            )
    conn.commit()
    logger.info(
        "PRICE_UPDATE applied to product '%s' (price=%.2f %s)", product_id, price, currency
    )


# ---------------------------------------------------------------------------
# DLQ
# ---------------------------------------------------------------------------
def _send_to_dlq(event: dict, reason: str) -> None:
    product_id = event.get("id", "unknown")
    logger.error("Routing product '%s' to DLQ '%s'. Reason: %s", product_id, DLQ_TOPIC, reason)
    producer.send(DLQ_TOPIC, event)
    producer.flush()


# ---------------------------------------------------------------------------
# Main event processing
# ---------------------------------------------------------------------------
def process_event(event: dict) -> None:
    product_id = event.get("id")
    if not product_id:
        INGESTION_EVENTS_TOTAL.labels(event_type="UNKNOWN", outcome="skipped").inc()
        logger.warning("Malformed event — missing 'id'. Skipping: %s", event)
        return

    event_type = (event.get("eventType") or "FULL_UPDATE").upper()

    if event_type == "FULL_UPDATE":
        if not event.get("name"):
            INGESTION_EVENTS_TOTAL.labels(event_type=event_type, outcome="dlq").inc()
            logger.warning(
                "Malformed FULL_UPDATE — missing 'name' for id='%s'. Sending to DLQ.", product_id
            )
            _send_to_dlq(event, "missing 'name' field")
            return
        doc = _build_denormalized_doc(event)
        _upsert_full(event, doc)
        INGESTION_EVENTS_TOTAL.labels(event_type=event_type, outcome="processed").inc()

    elif event_type == "PRICE_UPDATE":
        if event.get("price") is None:
            INGESTION_EVENTS_TOTAL.labels(event_type=event_type, outcome="dlq").inc()
            logger.warning(
                "Malformed PRICE_UPDATE — missing 'price' for id='%s'. Sending to DLQ.", product_id
            )
            _send_to_dlq(event, "missing 'price' field")
            return
        _update_price(event)
        INGESTION_EVENTS_TOTAL.labels(event_type=event_type, outcome="processed").inc()

    else:
        INGESTION_EVENTS_TOTAL.labels(event_type=event_type, outcome="skipped").inc()
        logger.warning(
            "Unknown eventType '%s' for id='%s'. Skipping.", event_type, product_id
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    start_http_server(METRICS_PORT)
    logger.info("Prometheus metrics server listening on port %d", METRICS_PORT)
    logger.info("Waiting %d s for Kafka to be ready …", KAFKA_READY_WAIT)
    time.sleep(KAFKA_READY_WAIT)

    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="ingestion-worker",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        session_timeout_ms=30_000,
        heartbeat_interval_ms=10_000,
    )
    logger.info("Ingestion worker listening on topic '%s'", TOPIC)

    for message in consumer:
        event = message.value
        logger.info(
            "Received event — id='%s' eventType='%s'",
            event.get("id"), event.get("eventType", "FULL_UPDATE"),
        )
        try:
            process_event(event)
        except psycopg2.Error as exc:
            logger.error("DB error for product '%s': %s", event.get("id"), exc)
            conn.rollback()
            INGESTION_EVENTS_TOTAL.labels(
                event_type=(event.get("eventType") or "FULL_UPDATE").upper(),
                outcome="db_error",
            ).inc()
            _send_to_dlq(event, str(exc))
        except Exception as exc:
            logger.error("Unexpected error for product '%s': %s", event.get("id"), exc)
            INGESTION_EVENTS_TOTAL.labels(
                event_type=(event.get("eventType") or "FULL_UPDATE").upper(),
                outcome="error",
            ).inc()
            _send_to_dlq(event, str(exc))


if __name__ == "__main__":
    main()
