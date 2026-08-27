# Railway Dockerfile — if you prefer Docker over Nixpacks
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for psycopg2, xhtml2pdf, PyPDF2
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy project
COPY . .

# Create volume-aware dirs — Railway Volume mounts at /data
RUN mkdir -p /data/uploads/resumes /data/reports /data/exports \
    && mkdir -p backend/uploads/resumes backend/reports backend/exports backend/instance

EXPOSE 5001

# Default: web. Railway worker/beat services override CMD. (1 worker for free tier)
CMD ["sh", "-c", "gunicorn --chdir backend --workers 1 --threads 2 --timeout 120 --bind 0.0.0.0:$PORT app:app"]
