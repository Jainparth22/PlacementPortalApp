#!/bin/sh
# Usage: entrypoint.sh web|worker|beat|flower|migrate|seed
set -e

PORT="${PORT:-5001}"

case "$1" in
  web)
    # Apply schema migrations before serving (set RUN_MIGRATIONS=0 to skip, e.g. for extra web replicas)
    if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
      echo "[entrypoint] flask db upgrade"
      flask --app backend/app.py db upgrade
    fi
    # gthread + many threads: each open SSE live-notification stream holds one thread (SSE_MAX_CONNECTIONS caps it)
    # prometheus_client multiprocess mode: counters/histograms are aggregated across gunicorn workers
    export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/prom}"
    rm -rf "$PROMETHEUS_MULTIPROC_DIR" && mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
    export OTEL_SERVICE_NAME="${OTEL_SERVICE_NAME:-ppa-web}"
    exec gunicorn -c docker/gunicorn.conf.py --chdir backend --worker-class gthread \
      --workers "${WEB_CONCURRENCY:-2}" --threads "${WEB_THREADS:-32}" \
      --timeout 120 --graceful-timeout 30 \
      --access-logfile - --bind "0.0.0.0:${PORT}" app:app
    ;;
  worker)
    export OTEL_SERVICE_NAME="${OTEL_SERVICE_NAME:-ppa-worker}"
    # prefork pool; SIGTERM = warm shutdown (finish the running task, then exit)
    exec celery --workdir backend -A celery_worker worker \
      --loglevel="${CELERY_LOG_LEVEL:-info}" --concurrency="${CELERY_CONCURRENCY:-2}" -Q ppa
    ;;
  beat)
    exec celery --workdir backend -A celery_worker beat \
      --loglevel="${CELERY_LOG_LEVEL:-info}" --schedule /tmp/celerybeat-schedule
    ;;
  flower)
    exec celery --workdir backend -A celery_worker flower --port=5555
    ;;
  migrate)
    exec flask --app backend/app.py db upgrade
    ;;
  seed)
    exec python seed.py
    ;;
  *)
    exec "$@"
    ;;
esac
