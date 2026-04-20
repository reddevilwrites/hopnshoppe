# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching.
# --mount=type=cache keeps pip's download cache on the host between builds so
# packages are not re-downloaded from PyPI on every requirements.txt change.
# The cache is never written into the image layer (same net image size as
# --no-cache-dir), but cold builds are significantly faster.
# Requires BuildKit, which docker compose v2 enables by default.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Bake the embedding model at build time.
# - Avoids runtime network dependency (model is baked into the image)
# - HF_HOME points to /app/models so the cache lands in a path we control
# - EMBED_MODEL is a build arg so the model can be changed without touching code
ARG EMBED_MODEL=BAAI/bge-base-en-v1.5
ENV HF_HOME=/app/models
ENV EMBED_MODEL=${EMBED_MODEL}
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBED_MODEL}')"

COPY main.py .
COPY scripts ./scripts

# Non-root user — consistent with the rest of the stack.
# chown /app so appuser can read the baked-in model cache at runtime.
RUN useradd -r -s /bin/false appuser && chown -R appuser /app
USER appuser

EXPOSE 8085

# Unbuffered output so logs appear immediately in docker compose logs
CMD ["python", "-u", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8085"]
