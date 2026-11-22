import logging
import os
import sys
import time
import jwt
from flask import Flask, Response, render_template, jsonify, request, send_file, current_app, g
from flask_cors import CORS
from flask_mail import Mail
from flask_migrate import Migrate
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone

from config import Config
from logging_config import setup_logging, request_id_var, new_request_id, log_event
from models import db, User, Notification, AsyncJob
from auth import generate_token, login_required
from cache import cache_stats, redis_health
import ratelimit
from storage import get_storage
import sessions
import events
import metrics
from tracing import init_tracing
from validators import validate_email

mail = Mail()
migrate = Migrate()
log = logging.getLogger('ppa')

API_VERSION = 'v1'
# Not versioned: documentation endpoints
_UNVERSIONED_API = ('/api/docs', '/api/swagger', '/api/openapi.yaml')

# Used to equalise login timing when the account does not exist (avoids user enumeration by latency)
_DUMMY_HASH = generate_password_hash('not-a-real-password')


class ApiVersionMiddleware:
    """Serve ``/api/v1/<x>`` from the same routes as ``/api/<x>`` (unversioned paths stay as a deprecated alias)."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        prefix = f'/api/{API_VERSION}/'
        if path.startswith(prefix):
            environ['PATH_INFO'] = '/api/' + path[len(prefix):]
            environ['PPA_API_VERSIONED'] = '1'
        return self.wsgi_app(environ, start_response)


def _init_sentry(app):
    dsn = app.config.get('SENTRY_DSN')
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.celery import CeleryIntegration
        sentry_sdk.init(dsn=dsn, integrations=[FlaskIntegration(), CeleryIntegration()],
                        environment=app.config.get('ENV_NAME'), traces_sample_rate=0.0, send_default_pii=False)
        log.info('sentry_enabled')
    except ImportError:
        log.warning('sentry_sdk_not_installed')


BASELINE_REVISION = '0001'
MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), '..', 'migrations')


def _auto_migrate(app):
    from flask_migrate import upgrade, stamp
    try:
        tables = set(inspect(db.engine).get_table_names())
        if 'users' in tables and 'alembic_version' not in tables:
            stamp(directory=MIGRATIONS_DIR, revision=BASELINE_REVISION)   # legacy create_all() database
            log.info('legacy_db_stamped')
        upgrade(directory=MIGRATIONS_DIR)
    except Exception:  # noqa: BLE001
        log.exception('auto_migrate_failed')


def _bootstrap_database(app):
    """Create folders, (dev) tables, the admin user and optional demo data."""
    os.makedirs(os.path.join(app.config.get('UPLOAD_FOLDER', 'uploads'), 'resumes'), exist_ok=True)
    os.makedirs(app.config.get('REPORTS_FOLDER', os.path.join(os.path.dirname(__file__), 'reports')), exist_ok=True)
    os.makedirs(app.config.get('EXPORTS_FOLDER', os.path.join(os.path.dirname(__file__), 'exports')), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), 'instance'), exist_ok=True)

    # Schema is managed by Alembic (Flask-Migrate). In dev AUTO_MIGRATE=1 applies pending migrations
    # on boot (databases created by the old db.create_all() are stamped at the baseline first).
    # In production set AUTO_MIGRATE=0 and run `flask db upgrade` explicitly (the Docker entrypoint does).
    if app.config.get('AUTO_MIGRATE') and not os.path.basename(sys.argv[0] or '').startswith('flask'):
        _auto_migrate(app)

    try:
        admin = User.query.filter_by(role='admin').first()
        if not admin:
            db.session.add(User(
                email=app.config['ADMIN_EMAIL'],
                password_hash=generate_password_hash(app.config['ADMIN_PASSWORD']),
                role='admin', is_active=True,
            ))
            db.session.commit()
            log_event(log, 'admin_created')

        # Auto-seed demo data if the DB is empty (AUTO_SEED=0 disables)
        if os.environ.get('AUTO_SEED', '1') == '1':
            from models import CompanyProfile, StudentProfile
            if CompanyProfile.query.count() == 0 and StudentProfile.query.count() == 0:
                log.info('auto_seed_start')
                orig = os.environ.get('AUTO_SEED')
                os.environ['AUTO_SEED'] = '0'   # seed() calls create_app(); prevent recursion
                try:
                    import SampleDataSeed
                    SampleDataSeed.seed()
                finally:
                    if orig is None:
                        os.environ.pop('AUTO_SEED', None)
                    else:
                        os.environ['AUTO_SEED'] = orig
                log.info('auto_seed_done')
    except SQLAlchemyError as e:
        db.session.rollback()
        log.warning('schema_not_ready_run_flask_db_upgrade', extra={'event': 'schema_not_ready', 'error': str(e)[:200]})
    except Exception as e:  # noqa: BLE001 - seeding must never stop the app booting
        db.session.rollback()
        log.warning('bootstrap_skipped', extra={'event': 'bootstrap_skipped', 'error': str(e)[:200]})


def create_app(config_overrides=None):
    app = Flask(__name__,
                static_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend', 'static'),
                template_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend', 'templates'))
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)

    setup_logging(app.config['LOG_LEVEL'], app.config['LOG_JSON'])
    _init_sentry(app)

    # Trust only N reverse-proxy hops for the client IP (default 0: use the socket address).
    hops = app.config['TRUSTED_PROXY_COUNT']
    if hops > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)
    app.wsgi_app = ApiVersionMiddleware(app.wsgi_app)

    db.init_app(app)
    mail.init_app(app)
    metrics.instrument(app)
    init_tracing(app)
    migrate.init_app(app, db, directory=MIGRATIONS_DIR)
    if app.config.get('CORS_ORIGINS'):
        CORS(app, resources={r"/api/*": {"origins": app.config['CORS_ORIGINS']}})

    from routes.admin import admin_bp
    from routes.company import company_bp
    from routes.student import student_bp
    app.register_blueprint(admin_bp)
    app.register_blueprint(company_bp)
    app.register_blueprint(student_bp)

    try:
        from celery_worker import init_celery
        init_celery(app)
    except Exception as e:  # noqa: BLE001
        log.warning('celery_init_failed', extra={'event': 'celery_init_failed', 'error': str(e)[:200]})

    if not app.config.get('SKIP_BOOTSTRAP'):
        with app.app_context():
            _bootstrap_database(app)

    # ------------------------------------------------------------------ request hooks
    @app.before_request
    def _start_request():
        g.start_time = time.perf_counter()
        g.request_id = new_request_id(request.headers.get('X-Request-ID'))
        request_id_var.set(g.request_id)

    @app.after_request
    def _finish_request(resp):
        elapsed_ms = (time.perf_counter() - getattr(g, 'start_time', time.perf_counter())) * 1000
        resp.headers['X-Request-ID'] = getattr(g, 'request_id', '-')
        resp.headers['X-Response-Time'] = f'{elapsed_ms:.0f}ms'
        if request.path.startswith('/api/'):
            resp.headers['Cache-Control'] = 'no-store'     # API data is per-user / changes often
            if request.environ.get('PPA_API_VERSIONED'):
                resp.headers['X-API-Version'] = API_VERSION
            elif request.path not in _UNVERSIONED_API:
                resp.headers['Deprecation'] = 'true'
                resp.headers['Link'] = f'</api/{API_VERSION}{request.path[4:]}>; rel="successor-version"'
        if g.get('outbox_dirty'):
            try:
                events.relay_outbox(limit=50)      # push live events now; Celery beat relays whatever this misses
            except Exception:  # noqa: BLE001 - never fail a request because of the event bus
                db.session.rollback()
                log.warning('outbox_fast_relay_failed', exc_info=True)
        if elapsed_ms > 1000:
            log_event(log, 'slow_request', logging.WARNING, path=request.path, method=request.method, ms=round(elapsed_ms))
        return resp

    # ------------------------------------------------------------------ auth routes
    @app.route('/api/auth/login', methods=['POST'])
    def login():
        client_ip = request.remote_addr or 'unknown'
        allowed, retry_after = ratelimit.hit('login-ip', client_ip, app.config['LOGIN_RATE_LIMIT'])
        if not allowed:
            return ratelimit.too_many(retry_after, f"Too many login attempts ({app.config['LOGIN_RATE_LIMIT']}/min). Try again in {retry_after}s.")

        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        email = str(data.get('email', '')).strip()
        password = str(data.get('password', '')).strip()

        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        if not validate_email(email):
            return jsonify({'error': 'Invalid email format'}), 400

        # Per-account brute-force guard (counts failures only, so it can't be tripped by successful logins)
        failures, ttl = ratelimit.current('login-email', email.lower())
        if failures >= app.config['LOGIN_EMAIL_RATE_LIMIT']:
            return ratelimit.too_many(ttl, f'Too many failed attempts for this account. Try again in {ttl}s.')

        user = User.query.filter_by(email=email).first()
        if not user:
            check_password_hash(_DUMMY_HASH, password)
        if not user or not check_password_hash(user.password_hash, password):
            ratelimit.hit('login-email', email.lower(), app.config['LOGIN_EMAIL_RATE_LIMIT'])
            metrics.inc(metrics.LOGINS, 'failed')
            log_event(log, 'login_failed', logging.WARNING, ip=client_ip)
            return jsonify({'error': 'Invalid email or password'}), 401

        if not user.is_active:
            return jsonify({'error': 'Account is deactivated. Contact admin.'}), 403
        if user.is_blacklisted:
            return jsonify({'error': 'Account is blacklisted. Contact admin.'}), 403

        ratelimit.reset('login-email', email.lower())
        metrics.inc(metrics.LOGINS, 'success')
        user.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()

        response = _session_payload(user)
        response['message'] = 'Login successful'
        resp = jsonify(response)
        raw_refresh, _ = sessions.issue_refresh_token(user)
        db.session.commit()
        return sessions.set_session_cookies(resp, raw_refresh), 200

    def _session_payload(user):
        """Access token + user (+ profile): the body of login and refresh responses."""
        payload = {'token': generate_token(user), 'token_type': 'Bearer',
                   'expires_in': app.config['JWT_ACCESS_TOKEN_EXPIRES'], 'user': user.to_dict()}
        if user.role == 'student' and user.student_profile:
            payload['profile'] = user.student_profile.to_dict()
        elif user.role == 'company' and user.company_profile:
            payload['profile'] = user.company_profile.to_dict()
        return payload

    @app.route('/api/auth/refresh', methods=['POST'])
    def refresh():
        """Exchange the httpOnly refresh cookie for a new access token (and rotate the refresh token)."""
        if not sessions.csrf_ok():
            return jsonify({'error': 'CSRF check failed', 'code': 'csrf'}), 403
        try:
            user, new_raw = sessions.rotate_refresh_token(request.cookies.get(sessions.REFRESH_COOKIE))
        except sessions.RefreshError as e:
            resp = jsonify({'error': e.message, 'code': e.code})
            resp.status_code = 401
            if e.code != 'race':                 # a racing sibling tab just got fresh cookies: keep them
                sessions.clear_session_cookies(resp)
            return resp
        return sessions.set_session_cookies(jsonify(_session_payload(user)), new_raw), 200

    @app.route('/api/auth/logout', methods=['POST'])
    def logout():
        """Idempotent logout: blacklist the access token's jti, revoke the refresh-token family, clear cookies.
        Works even if the access token has already expired (the refresh cookie alone is enough)."""
        raw_refresh = request.cookies.get(sessions.REFRESH_COOKIE)
        if raw_refresh and not sessions.csrf_ok():
            return jsonify({'error': 'CSRF check failed', 'code': 'csrf'}), 403
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ', 1)[1].strip()
            try:
                payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'], options={"verify_exp": False})
                jti, exp = payload.get('jti'), payload.get('exp')
                if jti:
                    from auth import blacklist_token
                    blacklist_token(jti, exp)
            except Exception as e:  # noqa: BLE001
                log.warning('logout_blacklist_failed', extra={'event': 'logout_blacklist_failed', 'error': str(e)[:200]})
        if raw_refresh:
            from models import RefreshToken
            row = RefreshToken.query.filter_by(token_hash=sessions._hash(raw_refresh)).first()
            if row:
                sessions.revoke_family(row.family_id)
                db.session.commit()
        resp = jsonify({'message': 'Logged out successfully'})
        return sessions.clear_session_cookies(resp), 200

    @app.route('/api/auth/logout-all', methods=['POST'])
    @login_required
    def logout_all(user):
        """Revoke every session of the current user (all devices)."""
        sessions.revoke_all_for_user(user.id)
        db.session.commit()
        return sessions.clear_session_cookies(jsonify({'message': 'All sessions revoked'})), 200

    @app.route('/api/auth/me', methods=['GET'])
    @login_required
    def current_user_info(user):
        response = {'user': user.to_dict()}
        if user.role == 'student' and user.student_profile:
            response['profile'] = user.student_profile.to_dict()
        elif user.role == 'company' and user.company_profile:
            response['profile'] = user.company_profile.to_dict()
        return jsonify(response), 200

    # ------------------------------------------------------------------ notifications & jobs
    @app.route('/api/notifications', methods=['GET'])
    @login_required
    def get_notifications(user):
        from pagination import paginated_response
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        query = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc())
        return jsonify(paginated_response(query, page, per_page)), 200

    @app.route('/api/notifications/stream', methods=['GET'])
    @login_required
    def notification_stream(user):
        """Server-Sent Events: live notifications for the current user (resumable with Last-Event-ID)."""
        if not events.try_acquire_connection(app.config['SSE_MAX_CONNECTIONS']):
            resp = jsonify({'error': 'Live stream is at capacity, use polling', 'code': 'stream_full'})
            resp.status_code = 503
            resp.headers['Retry-After'] = '10'
            return resp
        last_id = request.headers.get('Last-Event-ID') or request.args.get('last_event_id')
        body = events.stream_notifications(user.id, last_id, app.config['SSE_MAX_SECONDS'])
        resp = Response(body, mimetype='text/event-stream')
        resp.headers['X-Accel-Buffering'] = 'no'          # tell nginx not to buffer the stream
        return resp

    @app.route('/api/notifications/<int:id>/read', methods=['PUT'])
    @login_required
    def mark_notification_read(user, id):
        notification = db.get_or_404(Notification, id)
        if notification.user_id != user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        notification.is_read = True
        db.session.commit()
        return jsonify({'message': 'Notification marked as read'}), 200

    @app.route('/api/notifications/read-all', methods=['PUT'])
    @login_required
    def mark_all_read(user):
        Notification.query.filter_by(user_id=user.id, is_read=False).update({'is_read': True})
        db.session.commit()
        return jsonify({'message': 'All notifications marked as read'}), 200

    @app.route('/api/jobs/<int:job_id>', methods=['GET'])
    @login_required
    def get_job_status(user, job_id):
        job = db.get_or_404(AsyncJob, job_id)
        if job.user_id != user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        return jsonify(job.to_dict()), 200

    # ------------------------------------------------------------------ health
    @app.route('/health')
    def health():
        try:
            db.session.execute(db.text('SELECT 1'))
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
        redis_state = redis_health()
        workers = 0
        if redis_state.get('state') == 'connected':
            from async_dispatch import worker_count
            workers = worker_count()
        status = 'ok' if db_ok else 'degraded'
        return jsonify({
            'status': status,
            'postgres' if 'postgresql' in app.config['SQLALCHEMY_DATABASE_URI'] else 'database': 'connected' if db_ok else 'down',
            'redis': redis_state,
            'celery': {'workers': workers, 'mode': 'async' if workers else 'sync-fallback'},
            'cache': cache_stats(),
            'storage': {'backend': get_storage().name, 'ok': get_storage().healthy()},
            'live_streams': events.active_connections(),
            'api_version': API_VERSION,
        }), (200 if db_ok else 503)

    # ------------------------------------------------------------------ docs
    @app.route('/api/openapi.yaml')
    def openapi_yaml():
        yaml_path = os.path.join(os.path.dirname(__file__), '..', 'api.yaml')
        if os.path.exists(yaml_path):
            return send_file(yaml_path, mimetype='text/yaml')
        return jsonify({'error': 'api.yaml not found'}), 404

    @app.route('/api/docs')
    def api_docs():
        html = """
        <!DOCTYPE html><html><head><title>PPA API Docs</title>
        <meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1">
        <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
        <style>body{margin:0;padding:0}</style>
        </head><body>
        <redoc spec-url='/api/openapi.yaml'></redoc>
        <script src="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js"></script>
        </body></html>
        """
        return html, 200, {'Content-Type': 'text/html'}

    @app.route('/api/swagger')
    def api_swagger():
        html = """
        <!DOCTYPE html><html><head><title>PPA Swagger</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"/>
        </head><body><div id="swagger-ui"></div>
        <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
        <script>
        window.onload = () => { SwaggerUIBundle({url: '/api/openapi.yaml', dom_id: '#swagger-ui'}); };
        </script></body></html>
        """
        return html, 200, {'Content-Type': 'text/html'}

    # ------------------------------------------------------------------ frontend + errors
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Not found'}), 404
        return render_template('index.html')

    @app.errorhandler(413)
    def too_large(e):
        return jsonify({'error': 'File too large (max 5 MB)'}), 413

    @app.errorhandler(Exception)
    def unhandled(e):
        if isinstance(e, HTTPException):
            return e
        log.exception('unhandled_exception', extra={'event': 'unhandled_exception', 'path': request.path})
        db.session.rollback()
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Internal server error', 'request_id': getattr(g, 'request_id', None)}), 500
        raise e

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    debug = Config.ENV_NAME != 'production'
    app.run(host='0.0.0.0', port=port, debug=debug)
