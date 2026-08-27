import jwt
import uuid
import datetime
from functools import wraps
from flask import request, jsonify, current_app
from models import User

# In-memory fallback for blacklist when Redis is down (single-web offline mode)
_blacklisted_memory = {}


def _is_blacklisted(jti):
    if not jti:
        return False
    # Redis check first
    try:
        from cache import get_redis
        r = get_redis()
        if r and r.exists(f"bl:{jti}"):
            return True
    except Exception:
        pass
    # Memory fallback
    exp = _blacklisted_memory.get(jti)
    if exp:
        if datetime.datetime.utcnow() < exp:
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
        exp_dt = datetime.datetime.utcfromtimestamp(exp)
    else:
        exp_dt = exp
    ttl = int((exp_dt - datetime.datetime.utcnow()).total_seconds())
    if ttl <= 0:
        ttl = 3600
    try:
        from cache import get_redis
        r = get_redis()
        if r:
            r.setex(f"bl:{jti}", ttl, "1")
            return
    except Exception:
        pass
    _blacklisted_memory[jti] = datetime.datetime.utcnow() + datetime.timedelta(seconds=ttl)


def generate_token(user):
    payload = {
        'user_id': user.id,
        'email': user.email,
        'role': user.role,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(
            seconds=current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
        ),
        'iat': datetime.datetime.utcnow(),
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
    user = User.query.get(payload['user_id'])
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
