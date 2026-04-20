"""
One-time migration: re-embed all search_index products with the current model.

Run after changing EMBED_MODEL (e.g. upgrading from 384-dim to 768-dim):

    docker exec hopnshoppe-search-service python scripts/re_embed.py

The script reads every row in search_index whose embedding IS NULL (or all rows
if --all is passed), computes a new embedding with the currently loaded model,
and updates the row in-place. Runs in batches to avoid holding a long transaction.
"""

import os
import sys
import time
import psycopg2
from sentence_transformers import SentenceTransformer

BATCH_SIZE = 50
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-base-en-v1.5")
DB_DSN = (
    f"host={os.environ.get('SEARCH_DB_HOST', 'search-db')} "
    f"port={os.environ.get('SEARCH_DB_PORT', '5432')} "
    f"dbname={os.environ.get('SEARCH_DB_NAME', 'search_db')} "
    f"user={os.environ.get('SEARCH_DB_USER', 'postgres')} "
    f"password={os.environ['SEARCH_DB_PASSWORD']}"
)

re_embed_all = "--all" in sys.argv

print(f"Loading model '{EMBED_MODEL}' …")
model = SentenceTransformer(EMBED_MODEL)
print("Model loaded.")

conn = psycopg2.connect(DB_DSN)
conn.autocommit = False

with conn.cursor() as cur:
    if re_embed_all:
        cur.execute("SELECT COUNT(*) FROM search_index")
    else:
        cur.execute("SELECT COUNT(*) FROM search_index WHERE embedding IS NULL")
    total = cur.fetchone()[0]

print(f"Products to re-embed: {total} ({'all' if re_embed_all else 'NULL embedding only'})")
if total == 0:
    print("Nothing to do.")
    conn.close()
    sys.exit(0)

where_clause = "" if re_embed_all else "WHERE embedding IS NULL"
processed = 0
t0 = time.monotonic()

with conn.cursor() as cur:
    cur.execute(f"SELECT product_id, search_text FROM search_index {where_clause}")
    rows = cur.fetchall()

with conn.cursor() as cur:
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        texts = [r[1] for r in batch]
        embeddings = model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=False)
        for (pid, _), emb in zip(batch, embeddings):
            vec_str = "[" + ",".join(f"{x:.8f}" for x in emb.tolist()) + "]"
            cur.execute(
                "UPDATE search_index SET embedding = %s::vector WHERE product_id = %s",
                (vec_str, pid),
            )
        conn.commit()
        processed += len(batch)
        elapsed = time.monotonic() - t0
        rate = processed / elapsed if elapsed > 0 else 0
        print(f"  {processed}/{total} ({rate:.1f} products/s)")

conn.close()
print(f"Done. Re-embedded {processed} products in {time.monotonic() - t0:.1f}s.")
