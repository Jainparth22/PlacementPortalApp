"""Refresh-token sessions: short-lived access JWT + rotating refresh token in an httpOnly cookie.

Threat model / design
---------------------
* Access token  : JWT, 15 min, sent as ``Authorization: Bearer`` and kept **in JS memory only** (not
  localStorage), so an XSS bug can't steal a long-lived credential from storage.
* Refresh token : 256-bit random opaque string in an ``httpOnly; SameSite=Strict; (Secure)`` cookie that
  JavaScript cannot read. Only its SHA-256 hash is stored (DB leak != usable tokens).
* Rotation      : every /auth/refresh issues a NEW refresh token and marks the old one used.
* Reuse detection: presenting an already-rotated token means it was copied (stolen) - the whole token
  *family* (one login) is revoked, forcing re-login on every device that shares it. A small grace window
  (``REFRESH_REUSE_GRACE_SECONDS``) tolerates two tabs refreshing at the same instant without punishing the
  legitimate user.
* CSRF          : cookie-authenticated endpoints (/auth/refresh, /auth/logout) require a double-submit
  token (``ppa_csrf`` cookie == ``X-CSRF-Token`` header, constant-time compare) plus an Origin check on top
  of SameSite=Strict. Bearer-authenticated endpoints aren't CSRF-able (browsers don't attach the header).
"""
import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import current_app, request

from models import db, RefreshToken, User

log = logging.getLogger(__name__)

REFRESH_COOKIE = 'ppa_refresh'
CSRF_COOKIE = 'ppa_csrf'
CSRF_HEADER = 'X-CSRF-Token'


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)      # naive UTC, like the DB columns


def _hash(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


# --------------------------------------------------------------------------- issue / rotate / revoke
def issue_refresh_token(user, family_id=None):
    raw = secrets.token_urlsafe(48)
    row = RefreshToken(
        user_id=user.id, family_id=family_id or str(uuid.uuid4()), token_hash=_hash(raw),
        expires_at=_now() + timedelta(days=current_app.config['REFRESH_TOKEN_DAYS']),
        user_agent=(request.headers.get('User-Agent') or '')[:200] if request else None,
        ip=(request.remote_addr or '')[:45] if request else None,
    )
    db.session.add(row)
    return raw, row


def revoke_family(family_id):
    now = _now()
    RefreshToken.query.filter_by(family_id=family_id, revoked_at=None).update({'revoked_at': now})


def revoke_all_for_user(user_id):
    RefreshToken.query.filter_by(user_id=user_id, revoked_at=None).update({'revoked_at': _now()})


class RefreshError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def rotate_refresh_token(raw):
    """Validate ``raw`` and return (user, new_raw_token). Raises RefreshError."""
    if not raw:
        raise RefreshError('missing', 'No refresh token')
    row = RefreshToken.query.filter_by(token_hash=_hash(raw)).first()
    now = _now()
    if row is None:
        raise RefreshError('invalid', 'Invalid refresh token')
    if row.revoked_at is not None:
        raise RefreshError('revoked', 'Session was revoked. Please log in again.')
    if row.expires_at <= now:
        raise RefreshError('expired', 'Session expired. Please log in again.')
    if row.used_at is not None:
        grace = timedelta(seconds=current_app.config['REFRESH_REUSE_GRACE_SECONDS'])
        if now - row.used_at <= grace:
            raise RefreshError('race', 'Refresh already in progress')             # benign: two tabs / retry
        revoke_family(row.family_id)                                                # reuse => assume theft
        db.session.commit()
        log.warning('refresh_token_reuse_detected', extra={'event': 'refresh_token_reuse_detected', 'user_id': row.user_id, 'family_id': row.family_id})
        raise RefreshError('reuse', 'Session revoked for your safety. Please log in again.')

    user = db.session.get(User, row.user_id)
    if not user or not user.is_active or user.is_blacklisted:
        revoke_family(row.family_id)
        db.session.commit()
        raise RefreshError('forbidden', 'Account is not active')

    row.used_at = now
    new_raw, _ = issue_refresh_token(user, family_id=row.family_id)
    db.session.commit()
    return user, new_raw


def purge_expired(older_than_days=1):
    """Housekeeping (Celery beat): delete tokens that expired more than a day ago."""
    cutoff = _now() - timedelta(days=older_than_days)
    n = RefreshToken.query.filter(RefreshToken.expires_at < cutoff).delete()
    db.session.commit()
    return n


# --------------------------------------------------------------------------- cookies + CSRF
def set_session_cookies(resp, raw_refresh):
    cfg = current_app.config
    max_age = cfg['REFRESH_TOKEN_DAYS'] * 86400
    common = dict(max_age=max_age, secure=cfg['COOKIE_SECURE'], samesite=cfg['COOKIE_SAMESITE'], path='/api/')
    resp.set_cookie(REFRESH_COOKIE, raw_refresh, httponly=True, **common)
    resp.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(24), httponly=False, **common)   # JS must read this one
    return resp


def clear_session_cookies(resp):
    for name in (REFRESH_COOKIE, CSRF_COOKIE):
        resp.delete_cookie(name, path='/api/')
    return resp


def _origin_ok():
    origin = request.headers.get('Origin')
    if not origin:
        return True            # same-origin GET/navigation or non-browser client
    allowed = set(current_app.config.get('CORS_ORIGINS') or [])
    host = urlparse(origin).netloc
    return origin in allowed or host == request.host


def csrf_ok():
    """Double-submit check for cookie-authenticated requests."""
    if not _origin_ok():
        return False
    cookie, header = request.cookies.get(CSRF_COOKIE), request.headers.get(CSRF_HEADER)
    return bool(cookie) and bool(header) and hmac.compare_digest(cookie, header)
