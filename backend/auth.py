import jwt
import uuid
import datetime
import logging
from functools import wraps
from flask import request, jsonify, current_app
from models import db, User
from cache import _call

log = logging.getLogger(__name__)

# In-memory fallback for blacklist when Redis is down (single-process offline mode)
_blacklisted_memory = {}


def _is_blacklisted(jti):
    if not jti:
        return False
    # Durable state Redis first
    found, ok = _call('state', lambda r: r.exists(f"bl:{jti}"))
    if ok and found:
        return True
    if not ok:
        log.warning('blacklist_check_degraded', extra={'event': 'blacklist_check_degraded'})
    # Memory fallback
    exp = _blacklisted_memory.get(jti)
    if exp:
        if _now() < exp:
            return True
        else:
            _blacklisted_memory.pop(jti, None)
    return False


def blacklist_token(jti, exp):
    """Blacklist jti until exp (datetime). Uses Redis TTL or in-memory."""
    if not jti or not exp:
        return
    # exp may be int timestamp or datetime
    if isinstance(exp, (int, float)):
        exp_dt = datetime.datetime.fromtimestamp(exp, tz=datetime.timezone.utc)
    else:
        exp_dt = exp if exp.tzinfo else exp.replace(tzinfo=datetime.timezone.utc)
    ttl = int((exp_dt - _now()).total_seconds())
    if ttl <= 0:
        ttl = 3600
    _, ok = _call('state', lambda r: r.set(f"bl:{jti}", "1", ex=ttl))
    if ok:
        return
    _blacklisted_memory[jti] = _now() + datetime.timedelta(seconds=ttl)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def generate_token(user):
    payload = {
        'user_id': user.id,
        'email': user.email,
        'role': user.role,
        'exp': _now() + datetime.timedelta(seconds=current_app.config['JWT_ACCESS_TOKEN_EXPIRES']),
        'iat': _now(),
        'jti': str(uuid.uuid4()),
    }
    token = jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')
    return token


def decode_token(token):
    try:
        payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
        # Stateful logout check — if jti is blacklisted, reject even if not expired
        if _is_blacklisted(payload.get('jti')):
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_current_user():
    # get user from jwt token in Authorization header
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None
    token = auth_header.split(' ')[1]
    payload = decode_token(token)
    if not payload:
        return None
    user = db.session.get(User, payload["user_id"])
    if user and user.is_active and not user.is_blacklisted:
        return user
    return None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        return f(user, *args, **kwargs)
    return decorated


def role_required(*roles):
    # decorator - checks if user has one of the required roles
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({'error': 'Authentication required'}), 401
            if user.role not in roles:
                return jsonify({'error': 'Insufficient permissions'}), 403
            return f(user, *args, **kwargs)
        return decorated
    return decorator
