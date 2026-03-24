FROM python:3.11-slim

# System dependencies for pdfplumber + reportlab + healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpoppler-cpp-dev \
    poppler-utils \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (cached layer — only rebuilds when requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and data files
COPY . .

# ── Bake regulatory knowledge base into the image ────────────────────────────
# Runs at build time so containers start with a warm ChromaDB index.
# sentence-transformers model is downloaded here (~100 MB, cached in image).
# No API keys required — embeddings use local sentence-transformers.
RUN python main.py migrate-db && python main.py index-kb

# ── Runtime configuration ─────────────────────────────────────────────────────
ENV LOG_LEVEL=INFO
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check via the /health endpoint (curl installed above)
HEALTHCHECK --interval=30s --timeout=15s --start-period=60s --retries=3 \
  CMD curl -sf http://localhost:${PORT:-8000}/health | grep -q '"status":"ok"' || exit 1

EXPOSE 8000

# serve.py reads $PORT from environment — no --port arg needed
ENTRYPOINT ["python", "serve.py"]
CMD ["--host", "0.0.0.0"]
