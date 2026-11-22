"""Structured logging + request-id propagation.

* ``setup_logging(app)`` configures the root logger (JSON in production, readable text in dev).
* ``request_id_var`` carries the current request id; it is attached to every log record, copied
  into Celery task headers (see celery_worker.py) and returned as ``X-Request-ID``.
* ``log_event(logger, "event_name", key=value)`` emits a record whose JSON has an ``event`` field
  plus arbitrary context, e.g. ``log_event(log, "hf_api_fallback", student_id=3, reason="timeout")``.
"""
import contextvars
import json
import logging
import sys
import time
import uuid

request_id_var = contextvars.ContextVar('request_id', default='-')

_RESERVED = set(logging.LogRecord('', 0, '', 0, '', (), None).__dict__) | {'message', 'asctime', 'request_id', 'event', 'trace_id'}


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_var.get()
        try:                                   # join logs with traces when OpenTelemetry is active
            from tracing import current_trace_id
            record.trace_id = current_trace_id()
        except Exception:  # noqa: BLE001
            record.trace_id = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            'ts': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(record.created)) + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'request_id': getattr(record, 'request_id', '-'),
            **({'trace_id': record.trace_id} if getattr(record, 'trace_id', None) else {}),
            'event': getattr(record, 'event', None) or record.getMessage(),
        }
        if getattr(record, 'event', None) and record.getMessage() != record.event:
            payload['message'] = record.getMessage()
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith('_'):
                payload[key] = value
        if record.exc_info:
            payload['exc'] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level='INFO', json_logs=False):
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        if getattr(h, '_ppa', False):
            root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler._ppa = True
    handler.addFilter(RequestIdFilter())
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s'))
    root.addHandler(handler)
    # noisy libraries
    for noisy in ('urllib3', 'httpx', 'httpcore', 'gradio_client'):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(logger, event, level=logging.INFO, **fields):
    """Emit a structured event. ``fields`` become top-level keys in JSON logs."""
    logger.log(level, event, extra={'event': event, **{k: v for k, v in fields.items() if k not in _RESERVED}})


def new_request_id(incoming=None):
    """Accept a sane client-supplied id (for cross-service tracing) or mint a new one."""
    if incoming and 8 <= len(incoming) <= 64 and all(c.isalnum() or c in '-_' for c in incoming):
        return incoming
    return uuid.uuid4().hex
