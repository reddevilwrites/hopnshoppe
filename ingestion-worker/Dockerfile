FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the embedding model at build time.
# - Avoids runtime network dependency (model is baked into the image)
# - HF_HOME points to /app/models so the cache lands in a path we control
# - EMBED_MODEL is a build arg so the model can be changed without touching code
ARG EMBED_MODEL=BAAI/bge-base-en-v1.5
ENV HF_HOME=/app/models
ENV EMBED_MODEL=${EMBED_MODEL}
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBED_MODEL}')"

COPY main.py .

# Non-root user — consistent with the rest of the stack.
# chown /app so appuser can read the baked-in model cache at runtime.
RUN useradd -r -s /bin/false appuser && chown -R appuser /app
USER appuser

# Unbuffered output so logs appear immediately in docker compose logs
CMD ["python", "-u", "main.py"]
