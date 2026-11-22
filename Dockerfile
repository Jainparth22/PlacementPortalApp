# One image, several roles (web / worker / beat / flower) selected by docker/entrypoint.sh
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    PORT=5001

WORKDIR /app

# libpq for psycopg2, build tools for wheels that need compiling (xhtml2pdf deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .
RUN sed -i 's/\r$//' docker/entrypoint.sh && chmod +x docker/entrypoint.sh \
    && useradd --create-home --uid 1000 ppa \
    && mkdir -p /data/uploads/resumes /data/reports /data/exports backend/instance \
    && chown -R ppa:ppa /data /app

USER ppa
VOLUME ["/data"]
EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','5001'), timeout=4)" || exit 1

ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["web"]
