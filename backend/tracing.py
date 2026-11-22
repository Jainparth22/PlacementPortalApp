"""OpenTelemetry distributed tracing (optional; off unless configured).

Enable by setting an OTLP endpoint, e.g. ``OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318``
(``OTEL_SERVICE_NAME`` names the process: ``ppa-web`` / ``ppa-worker``; sampling via ``OTEL_TRACES_SAMPLER_ARG``).

What you get
* one trace per request: Flask route span -> SQLAlchemy query spans -> Redis command spans -> outgoing HTTP
  (HuggingFace ATS) -> and, across the queue, the Celery publish span and the worker's task span, all under
  the SAME trace id (context is propagated in the task headers by the Celery instrumentation);
* the trace id is added to every JSON log line (``trace_id``) so logs and traces can be joined.

Everything is imported lazily, so the app runs fine without the opentelemetry packages installed.
"""
import logging
import os

log = logging.getLogger(__name__)

_initialised = False


def init_tracing(app, exporter=None, force=False):
    """Instrument the Flask app. ``exporter`` lets tests inject an in-memory exporter."""
    global _initialised
    endpoint = os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT')
    if _initialised or not (endpoint or exporter or force):
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    except ImportError as e:
        log.warning('tracing_disabled_missing_packages', extra={'event': 'tracing_disabled', 'error': str(e)[:120]})
        return False

    ratio = float(os.environ.get('OTEL_TRACES_SAMPLER_ARG', '1.0'))
    provider = TracerProvider(
        resource=Resource.create({'service.name': os.environ.get('OTEL_SERVICE_NAME', 'ppa-web'),
                                  'deployment.environment': app.config.get('ENV_NAME', 'development')}),
        sampler=ParentBased(TraceIdRatioBased(ratio)),
    )
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))   # endpoint/headers come from OTEL_* env
    trace.set_tracer_provider(provider)

    FlaskInstrumentor().instrument_app(app, excluded_urls='health,metrics,static')
    RedisInstrumentor().instrument()
    RequestsInstrumentor().instrument()
    with app.app_context():
        from models import db
        SQLAlchemyInstrumentor().instrument(engine=db.engine)
    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        CeleryInstrumentor().instrument()
    except Exception as e:  # noqa: BLE001
        log.warning('celery_tracing_unavailable', extra={'event': 'celery_tracing_unavailable', 'error': str(e)[:120]})
    _initialised = True
    log.info('tracing_enabled', extra={'event': 'tracing_enabled', 'sample_ratio': ratio})
    return True


def current_trace_id():
    """Hex trace id of the active span, or None (used by the log formatter)."""
    try:
        from opentelemetry import trace
        ctx = trace.get_current_span().get_span_context()
        return format(ctx.trace_id, '032x') if ctx and ctx.is_valid else None
    except Exception:  # noqa: BLE001
        return None


def uninstrument():
    """Tests only: undo global instrumentation."""
    global _initialised
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        RedisInstrumentor().uninstrument()
        RequestsInstrumentor().uninstrument()
        SQLAlchemyInstrumentor().uninstrument()
    except Exception:  # noqa: BLE001
        pass
    _initialised = False
