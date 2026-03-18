FROM python:3.11-slim

# System dependencies for pdfplumber + reportlab
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpoppler-cpp-dev \
    poppler-utils \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create required runtime directories
RUN mkdir -p output logs chroma_db

# Default environment
ENV LOG_LEVEL=INFO
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check — verify engine can load rules
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "from src.engine.decision_engine import DecisionEngine; DecisionEngine()" || exit 1

EXPOSE 8000

# Default: start the API server
ENTRYPOINT ["python", "serve.py"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
