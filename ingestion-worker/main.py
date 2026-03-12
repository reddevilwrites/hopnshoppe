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

import psycopg2
import psycopg2.extras
from bs4 import BeautifulSoup
from kafka import KafkaConsumer, KafkaProducer
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
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

EMBED_MODEL        = "all-MiniLM-L6-v2"   # 384-dimensional, lightweight, fast
KAFKA_READY_WAIT   = 15                    # seconds before starting consumer

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
            conn.autocommit = False
            logger.info("Connected to search-db on attempt %d", attempt)
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
        logger.warning("Malformed event — missing 'id'. Skipping: %s", event)
        return

    event_type = (event.get("eventType") or "FULL_UPDATE").upper()

    if event_type == "FULL_UPDATE":
        if not event.get("name"):
            logger.warning(
                "Malformed FULL_UPDATE — missing 'name' for id='%s'. Sending to DLQ.", product_id
            )
            _send_to_dlq(event, "missing 'name' field")
            return
        doc = _build_denormalized_doc(event)
        _upsert_full(event, doc)

    elif event_type == "PRICE_UPDATE":
        if event.get("price") is None:
            logger.warning(
                "Malformed PRICE_UPDATE — missing 'price' for id='%s'. Sending to DLQ.", product_id
            )
            _send_to_dlq(event, "missing 'price' field")
            return
        _update_price(event)

    else:
        logger.warning(
            "Unknown eventType '%s' for id='%s'. Skipping.", event_type, product_id
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
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
            _send_to_dlq(event, str(exc))
        except Exception as exc:
            logger.error("Unexpected error for product '%s': %s", event.get("id"), exc)
            _send_to_dlq(event, str(exc))


if __name__ == "__main__":
    main()
