FROM python:3.11-slim

# OCR system dependencies (Hebrew + English)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-heb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies before copying source (layer cache)
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

# Copy application source
COPY src/ src/
COPY migrations/ migrations/
COPY alembic.ini .

# Persistent storage for the SQLite database
VOLUME ["/data"]

ENV DATABASE_URL=sqlite:////data/smarttender.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "src.smarttender.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
