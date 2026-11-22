"""``Idempotency-Key`` support for POST endpoints (Stripe-style).

    @student_bp.route('/api/student/apply/<int:drive_id>', methods=['POST'])
    @role_required('student')
    @idempotent
    def apply_for_drive(user, drive_id): ...

Client sends ``Idempotency-Key: <uuid>`` on a POST. Retrying the same request (network blip, double click,
impatient proxy) returns the ORIGINAL response instead of performing the action twice.

Semantics
* Scope: (user, method, path, key). A key can't leak another user's response.
* First request atomically claims the key (``SET NX``) for 60 s ("in flight").
* Same key while the first is still running            -> 409 ``request_in_progress`` (+ Retry-After).
* Same key + same body after completion                -> stored response replayed, header ``Idempotent-Replay: true``.
* Same key + DIFFERENT body                            -> 422 (client bug: key reuse).
* 2xx and 4xx responses are stored 24 h (they're deterministic). 5xx / 429 are NOT stored, the key is released
  so the client can safely retry.
* No header -> behaves exactly as before (opt-in), so old clients keep working.
State lives in the durable "state" Redis (memory fallback when Redis is down - then it is per-process only).
"""
import hashlib
import json
import logging
import re
from functools import wraps

from flask import jsonify, make_response, request

from cache import _call, _MemoryStore
import metrics

log = logging.getLogger(__name__)

HEADER = 'Idempotency-Key'
_KEY_RE = re.compile(r'^[A-Za-z0-9._:-]{8,128}$')
IN_FLIGHT_TTL = 60
RESULT_TTL = 24 * 3600
_memory = _MemoryStore(max_items=2048)


def _store_get(key):
    raw, ok = _call('state', lambda r: r.get(key))
    return raw if ok else _memory.get(key)


def _claim(key, fingerprint):
    payload = json.dumps({'state': 'in_flight', 'fp': fingerprint})
    res, ok = _call('state', lambda r: r.set(key, payload, nx=True, ex=IN_FLIGHT_TTL))
    return bool(res) if ok else _memory.set_nx(key, payload, IN_FLIGHT_TTL)


def _store_set(key, payload, ttl):
    _, ok = _call('state', lambda r: r.set(key, payload, ex=ttl))
    if not ok:
        _memory.set(key, payload, ttl)


def _store_del(key):
    _call('state', lambda r: r.delete(key))
    _memory.delete(key)


def idempotent(f):
    @wraps(f)
    def wrapper(user, *args, **kwargs):
        idem = request.headers.get(HEADER)
        if not idem:
            return f(user, *args, **kwargs)
        if not _KEY_RE.match(idem):
            return jsonify({'error': f'Invalid {HEADER} (8-128 chars: letters, digits, . _ : -)'}), 400

        fingerprint = hashlib.sha256(request.get_data() or b'').hexdigest()
        key = f"ppa:idem:{user.id}:{request.method}:{request.path}:{idem}"

        if not _claim(key, fingerprint):
            stored = _store_get(key)
            data = json.loads(stored) if stored else None
            if data is None:                                     # expired between claim and read: just run it
                return f(user, *args, **kwargs)
            if data.get('fp') != fingerprint:
                return jsonify({'error': f'{HEADER} was already used with a different request body'}), 422
            if data.get('state') == 'in_flight':
                resp = jsonify({'error': 'A request with this Idempotency-Key is still being processed', 'code': 'request_in_progress'})
                resp.status_code = 409
                resp.headers['Retry-After'] = '1'
                return resp
            resp = make_response(data['body'], data['status'])
            resp.headers['Content-Type'] = data.get('content_type', 'application/json')
            resp.headers['Idempotent-Replay'] = 'true'
            metrics.inc(metrics.IDEMPOTENT_REPLAYS)
            return resp

        try:
            resp = make_response(f(user, *args, **kwargs))
        except Exception:
            _store_del(key)                                      # crashed: let the client retry
            raise
        if resp.status_code >= 500 or resp.status_code == 429:
            _store_del(key)
            return resp
        if not resp.direct_passthrough:
            _store_set(key, json.dumps({
                'state': 'done', 'fp': fingerprint, 'status': resp.status_code,
                'body': resp.get_data(as_text=True), 'content_type': resp.content_type,
            }), RESULT_TTL)
        else:
            _store_del(key)
        resp.headers['Idempotency-Key'] = idem
        return resp
    return wrapper


def clear_memory():
    _memory.clear()

