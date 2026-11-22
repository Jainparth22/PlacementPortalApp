"""Live notifications: transactional outbox -> Redis Streams -> Server-Sent Events.

Flow
----
1. ``notify(user_id, message)`` inserts the ``Notification`` row AND an ``OutboxEvent`` row in the SAME
   database transaction as the business change (approve drive, apply, ...). Either both exist or neither does -
   there is no window where the DB says "approved" but the event is lost (the "dual write" problem).
2. A relay (``relay_outbox``) copies unpublished outbox rows into Redis Streams, then marks them published.
   It runs right after the request commits (fast path, ~ms latency) and every 30 s from Celery beat (safety
   net for crashes / Redis outages). Delivery is **at-least-once**: a crash between XADD and the DB update
   re-publishes, so consumers de-duplicate by notification id (the SPA does).
3. Per-user stream ``ppa:notif:<user_id>`` (capped, expiring) feeds the SSE endpoint. A global stream
   ``ppa:events`` (capped) is an audit/event log that future consumer groups can read.
4. SSE reconnects send ``Last-Event-ID`` (= the stream id) so a dropped connection resumes without gaps.

Fallbacks
---------
* Redis not configured: an in-process stream keeps the feature working in single-process dev.
* Redis temporarily down: rows stay in the outbox (nothing lost) and are relayed when it returns; connected
  clients fall back to polling ``GET /notifications``.
"""
import json
import logging
import re
import threading
import time
from collections import deque, defaultdict
from datetime import datetime, timezone

from flask import g, has_request_context

from cache import _call, _cfg
import metrics
from models import db, Notification, OutboxEvent

log = logging.getLogger(__name__)

USER_STREAM = 'ppa:notif:{}'
GLOBAL_STREAM = 'ppa:events'
USER_STREAM_MAXLEN = 100
USER_STREAM_TTL = 7 * 86400
GLOBAL_STREAM_MAXLEN = 10000
_ID_RE = re.compile(r'^\d+-\d+$')


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------- write side
def notify(user_id, message, channel='in-app'):
    """Create a notification + its outbox event in the caller's transaction (caller commits)."""
    n = Notification(user_id=user_id, message=message, channel=channel, is_sent=True)
    db.session.add(n)
    db.session.flush()                      # assigns n.id / created_at so the event payload is complete
    db.session.add(OutboxEvent(event_type='notification.created', user_id=user_id, payload=json.dumps(n.to_dict())))
    if has_request_context():
        g.outbox_dirty = True               # relay right after the response is produced (see app.py)
    return n


# --------------------------------------------------------------------------- in-process stream (fallback)
class _MemoryStreams:
    """Per-user append-only log with blocking reads. Same id format as Redis (<ms>-<seq>)."""

    def __init__(self):
        self.lock = threading.Condition()
        self.data = defaultdict(lambda: deque(maxlen=USER_STREAM_MAXLEN))   # user -> deque[(id_tuple, fields)]
        self.seq = 0
        self.seen_events = set()                                           # outbox ids already appended

    def append(self, user_id, fields, event_id):
        with self.lock:
            if event_id in self.seen_events:
                return None
            self.seen_events.add(event_id)
            if len(self.seen_events) > 5000:
                self.seen_events = set(list(self.seen_events)[-2500:])
            self.seq += 1
            sid = (int(time.time() * 1000), self.seq)
            self.data[user_id].append((sid, fields))
            self.lock.notify_all()
            return f'{sid[0]}-{sid[1]}'

    def latest(self, user_id):
        with self.lock:
            d = self.data.get(user_id)
            return f'{d[-1][0][0]}-{d[-1][0][1]}' if d else '0-0'

    def read(self, user_id, last_id, block_ms):
        last = tuple(int(x) for x in last_id.split('-'))
        deadline = time.monotonic() + block_ms / 1000
        with self.lock:
            while True:
                items = [(f'{i[0]}-{i[1]}', f) for i, f in self.data.get(user_id, ()) if i > last]
                if items:
                    return items
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self.lock.wait(remaining)

    def clear(self):
        with self.lock:
            self.data.clear()
            self.seen_events.clear()


memory_streams = _MemoryStreams()


# --------------------------------------------------------------------------- relay (outbox -> streams)
def _redis_configured():
    return bool(_cfg('STATE_REDIS_URL'))


def _publish(row):
    """Publish one outbox row. Returns True when it reached the durable transport (Redis, or memory when
    Redis isn't configured at all)."""
    fields = {'event_id': str(row.id), 'type': row.event_type, 'data': row.payload}

    def _xadd(r):
        pipe = r.pipeline()
        if row.user_id is not None:
            key = USER_STREAM.format(row.user_id)
            pipe.xadd(key, fields, maxlen=USER_STREAM_MAXLEN, approximate=True)
            pipe.expire(key, USER_STREAM_TTL)
        pipe.xadd(GLOBAL_STREAM, {**fields, 'user_id': str(row.user_id or '')}, maxlen=GLOBAL_STREAM_MAXLEN, approximate=True)
        pipe.execute()
        return True

    _, ok = _call('state', _xadd)
    # Always mirror into the local stream so SSE clients of THIS process get it even while Redis is down.
    if row.user_id is not None and not ok:
        memory_streams.append(row.user_id, fields, row.id)
    if ok:
        return True
    return not _redis_configured()          # no Redis at all => memory IS the transport => consider it published


def relay_outbox(limit=100):
    """Publish pending outbox rows (at-least-once). Safe to call concurrently/repeatedly. Returns #published."""
    rows = (OutboxEvent.query.filter(OutboxEvent.published_at.is_(None)).order_by(OutboxEvent.id).limit(limit).all())
    published = 0
    for row in rows:
        try:
            if not _publish(row):
                break                       # Redis down: keep the rest (order preserved), retry later
        except Exception:  # noqa: BLE001
            log.exception('outbox_publish_failed', extra={'event': 'outbox_publish_failed', 'outbox_id': row.id})
            break
        row.published_at = _now()
        published += 1
        metrics.inc(metrics.OUTBOX_PUBLISHED)
    if rows:
        db.session.commit()
    return published


def purge_published(older_than_days=7):
    from datetime import timedelta
    cutoff = _now() - timedelta(days=older_than_days)
    n = OutboxEvent.query.filter(OutboxEvent.published_at.isnot(None), OutboxEvent.published_at < cutoff).delete()
    db.session.commit()
    return n


# --------------------------------------------------------------------------- read side (SSE)
def resolve_start_id(user_id, last_event_id):
    """Where a connection starts reading: the client's Last-Event-ID if valid, else 'now' (only new events)."""
    if last_event_id and _ID_RE.match(last_event_id):
        return last_event_id

    def _latest(r):
        last = r.xrevrange(USER_STREAM.format(user_id), count=1)
        return last[0][0] if last else '0-0'

    res, ok = _call('state', _latest)
    return res if ok else memory_streams.latest(user_id)


def read_events(user_id, last_id, block_ms=1500):
    """-> list of (stream_id, notification_dict). One bounded blocking read (< the Redis socket timeout)."""
    def _xread(r):
        out = r.xread({USER_STREAM.format(user_id): last_id}, block=block_ms, count=50)
        return out[0][1] if out else []

    entries, ok = _call('state', _xread)
    if not ok:
        entries = memory_streams.read(user_id, last_id if _ID_RE.match(last_id) else '0-0', block_ms)
    events = []
    for sid, fields in entries:
        try:
            events.append((sid, json.loads(fields['data'])))
        except (KeyError, ValueError):
            continue
    return events


_active = 0
_active_lock = threading.Lock()


def try_acquire_connection(limit):
    global _active
    with _active_lock:
        if _active >= limit:
            return False
        _active += 1
        return True


def release_connection():
    global _active
    with _active_lock:
        _active = max(0, _active - 1)


def active_connections():
    return _active


def sse_format(event, data, event_id=None):
    lines = []
    if event_id:
        lines.append(f'id: {event_id}')
    lines.append(f'event: {event}')
    lines.append(f'data: {json.dumps(data, separators=(",", ":"))}')
    return '\n'.join(lines) + '\n\n'


class _Releasing:
    """Iterator wrapper that frees the connection slot exactly once - even if the generator never started
    (client disconnected immediately), which a plain ``finally`` inside a generator would miss."""

    def __init__(self, gen):
        self.gen, self.released = gen, False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self.gen)
        except BaseException:
            self.close()
            raise

    def close(self):
        if not self.released:
            self.released = True
            self.gen.close()
            release_connection()


def _stream_gen(user_id, last_event_id, max_seconds, keepalive_seconds, block_ms):
    yield 'retry: 3000\n\n'
    last_id = resolve_start_id(user_id, last_event_id)
    yield sse_format('ready', {'user_id': user_id})
    started = last_sent = time.monotonic()
    while time.monotonic() - started < max_seconds:
        for sid, data in read_events(user_id, last_id, block_ms):
            last_id = sid
            yield sse_format('notification', data, sid)
            last_sent = time.monotonic()
        if time.monotonic() - last_sent >= keepalive_seconds:
            yield ': keep-alive\n\n'               # comment line: keeps proxies from closing an idle connection
            last_sent = time.monotonic()
    yield sse_format('reconnect', {'reason': 'max_duration'})         # client reconnects with Last-Event-ID


def stream_notifications(user_id, last_event_id, max_seconds, keepalive_seconds=15, block_ms=1500):
    """Body iterator for the SSE response. The caller must have called try_acquire_connection() first."""
    return _Releasing(_stream_gen(user_id, last_event_id, max_seconds, keepalive_seconds, block_ms))
