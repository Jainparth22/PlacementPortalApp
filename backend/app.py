import os
import jwt
from flask import Flask, render_template, jsonify, request, send_file, current_app
from flask_cors import CORS
from flask_mail import Mail
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

from config import Config
from models import db, User, StudentProfile, CompanyProfile, PlacementDrive, Application, Notification, AsyncJob
from auth import generate_token, get_current_user, login_required
from cache import cache_get, cache_set, cache_delete, get_redis
from validators import validate_email

mail = Mail()


def create_app():
    app = Flask(__name__,
                static_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend', 'static'),
                template_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend', 'templates'))
    app.config.from_object(Config)

    # Init extensions
    db.init_app(app)
    mail.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Register blueprints
    from routes.admin import admin_bp
    from routes.company import company_bp
    from routes.student import student_bp
    app.register_blueprint(admin_bp)
    app.register_blueprint(company_bp)
    app.register_blueprint(student_bp)

    # Init Celery
    try:
        from celery_worker import init_celery
        init_celery(app)
    except Exception as e:
        print(f'[!] Celery init failed: {e} - async tasks wont work')

    # Create tables and admin user — volume-aware for Railway
    with app.app_context():
        # Railway Volume: UPLOAD_FOLDER=/data/uploads, REPORTS_FOLDER=/data/reports, etc.
        os.makedirs(os.path.join(app.config.get('UPLOAD_FOLDER', 'uploads'), 'resumes'), exist_ok=True)
        os.makedirs(app.config.get('REPORTS_FOLDER', os.path.join(os.path.dirname(__file__), 'reports')), exist_ok=True)
        os.makedirs(app.config.get('EXPORTS_FOLDER', os.path.join(os.path.dirname(__file__), 'exports')), exist_ok=True)
        # SQLite instance dir (if using SQLite with volume, mount /data and set DATABASE_URL to sqlite:////data/ppa.db)
        instance_path = os.path.join(os.path.dirname(__file__), 'instance')
        # If DATABASE_URL points to /data, ensure that dir exists too
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if '/data/' in db_uri:
            try:
                os.makedirs('/data', exist_ok=True)
                os.makedirs(os.path.dirname(db_uri.split('///')[-1].split('?')[0]), exist_ok=True)
            except Exception:
                pass
        os.makedirs(instance_path, exist_ok=True)
        # Also ensure relative uploads folder exists for ATS fallback on ephemeral FS
        try:
            os.makedirs(os.path.join(os.path.dirname(__file__), 'uploads', 'resumes'), exist_ok=True)
        except Exception:
            pass

        db.create_all()

        # Create admin user if not exists
        admin = User.query.filter_by(role='admin').first()
        if not admin:
            admin = User(
                email=app.config['ADMIN_EMAIL'],
                password_hash=generate_password_hash(app.config['ADMIN_PASSWORD']),
                role='admin',
                is_active=True,
            )
            db.session.add(admin)
            db.session.commit()
            print(f"[+] Admin user created: {app.config['ADMIN_EMAIL']}")

        # Auto-seed demo data if empty (for recruiter demo — avoids empty dashboard)
        # Controlled by AUTO_SEED env (default 1). Calls SampleDataSeed which drops+recreates only if empty.
        if os.environ.get('AUTO_SEED', '1') == '1':
            try:
                from models import CompanyProfile, StudentProfile
                if CompanyProfile.query.count() == 0 and StudentProfile.query.count() == 0:
                    print("[*] No demo data found — auto-seeding from SampleDataSeed...")
                    # Prevent recursion: seed() calls create_app() which would auto-seed again
                    orig = os.environ.get('AUTO_SEED')
                    os.environ['AUTO_SEED'] = '0'
                    try:
                        import SampleDataSeed
                        SampleDataSeed.seed()
                    finally:
                        if orig is None:
                            os.environ.pop('AUTO_SEED', None)
                        else:
                            os.environ['AUTO_SEED'] = orig
                    print("[+] Auto-seed complete (8 accounts, 3 drives)")
            except Exception as e:
                print(f"[!] Auto-seed skipped: {e}")

    # Simple in-memory fallback for rate limit when Redis down
    _login_attempts = {}

    def _is_rate_limited(ip):
        """5 attempts per 60s per IP — uses Redis INCR if available, else in-memory."""
        try:
            r = get_redis()
            if r:
                key = f"ratelimit:login:{ip}"
                count = r.incr(key)
                if count == 1:
                    r.expire(key, 60)
                if count > 5:
                    return True
                return False
        except Exception:
            pass
        # fallback in-memory (single worker)
        from datetime import datetime as _dt
        now = _dt.utcnow()
        attempts = _login_attempts.get(ip, [])
        # keep only last 60s
        attempts = [t for t in attempts if (now - t).total_seconds() < 60]
        if len(attempts) >= 5:
            _login_attempts[ip] = attempts
            return True
        attempts.append(now)
        _login_attempts[ip] = attempts
        return False

    # TODO: move these to separate route files if app gets bigger

    # auth routes

    @app.route('/api/auth/login', methods=['POST'])
    def login():
        # Rate limiter — shows security maturity, prevents brute force
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr) or 'unknown'
        # X-Forwarded-For may contain list
        client_ip = client_ip.split(',')[0].strip()
        if _is_rate_limited(client_ip):
            return jsonify({'error': 'Too many login attempts. Try again in 60s.'}), 429

        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        email = data.get('email', '').strip()
        password = data.get('password', '').strip()

        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400

        if not validate_email(email):
            return jsonify({'error': 'Invalid email format'}), 400

        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({'error': 'Invalid email or password'}), 401

        if not user.is_active:
            return jsonify({'error': 'Account is deactivated. Contact admin.'}), 403

        if user.is_blacklisted:
            return jsonify({'error': 'Account is blacklisted. Contact admin.'}), 403

        user.last_login = datetime.utcnow()
        db.session.commit()

        token = generate_token(user)
        response = {
            'message': 'Login successful',
            'token': token,
            'user': user.to_dict(),
        }

        # Include profile info
        if user.role == 'student' and user.student_profile:
            response['profile'] = user.student_profile.to_dict()
        elif user.role == 'company' and user.company_profile:
            response['profile'] = user.company_profile.to_dict()

        return jsonify(response), 200

    @app.route('/api/auth/logout', methods=['POST'])
    @login_required
    def logout(user):
        # Stateful logout — blacklist jti until exp (was stateless before, token stayed valid 1h)
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ', 1)[1].strip()
            try:
                # Decode without exp check to get jti/exp even if close to expiry
                payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'], options={"verify_exp": False})
                jti = payload.get('jti')
                exp = payload.get('exp')
                if jti:
                    from auth import blacklist_token
                    blacklist_token(jti, exp)
            except Exception as e:
                print(f"[!] Logout blacklist failed: {e}")
        return jsonify({'message': 'Logged out successfully'}), 200

    @app.route('/api/auth/me', methods=['GET'])
    @login_required
    def current_user_info(user):
        response = {'user': user.to_dict()}
        if user.role == 'student' and user.student_profile:
            response['profile'] = user.student_profile.to_dict()
        elif user.role == 'company' and user.company_profile:
            response['profile'] = user.company_profile.to_dict()
        return jsonify(response), 200

    # notifications and jobs

    @app.route('/api/notifications', methods=['GET'])
    @login_required
    def get_notifications(user):
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        query = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc())
        # reuse pagination helper inline for app.py
        try:
            per_page = min(50, max(1, per_page))
            page = max(1, page)
            pagination = query.paginate(page=page, per_page=per_page, error_out=False)
            return jsonify({
                'items': [n.to_dict() for n in pagination.items],
                'total': pagination.total,
                'pages': pagination.pages,
                'page': pagination.page,
                'per_page': pagination.per_page,
                'has_next': pagination.has_next,
                'has_prev': pagination.has_prev,
            }), 200
        except Exception:
            notifications = query.limit(50).all()
            return jsonify([n.to_dict() for n in notifications]), 200

    @app.route('/api/notifications/<int:id>/read', methods=['PUT'])
    @login_required
    def mark_notification_read(user, id):
        notification = Notification.query.get_or_404(id)
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
        job = AsyncJob.query.get_or_404(job_id)
        if job.user_id != user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        return jsonify(job.to_dict()), 200

    # health check for Railway (and recruiter verification)
    @app.route('/health')
    def health():
        try:
            # DB check
            db.session.execute(db.text('SELECT 1'))
            db_ok = True
        except Exception:
            db_ok = False
        # Redis check (optional)
        try:
            from cache import get_redis
            r = get_redis()
            redis_ok = r is not None and r.ping()
        except Exception:
            redis_ok = False
        status = 'ok' if db_ok else 'degraded'
        code = 200 if db_ok else 500
        return jsonify({'status': status, 'db': db_ok, 'redis': redis_ok}), code

    # Interesting use of api.yaml — serve OpenAPI spec + ReDoc/Swagger UI (no extra deps)
    @app.route('/api/openapi.yaml')
    def openapi_yaml():
        # Serve api.yaml from project root
        yaml_path = os.path.join(os.path.dirname(__file__), '..', 'api.yaml')
        if os.path.exists(yaml_path):
            return send_file(yaml_path, mimetype='text/yaml')
        return jsonify({'error': 'api.yaml not found'}), 404

    @app.route('/api/docs')
    def api_docs():
        # ReDoc via CDN — recruiter can view all 53 endpoints without Postman
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

    # serve frontend

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Not found'}), 404
        return render_template('index.html')

    return app


app = create_app()

if __name__ == '__main__':
    # Railway injects PORT env; local uses 5001; host 0.0.0.0 for container
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_ENV') != 'production' and os.environ.get('RAILWAY_ENVIRONMENT') is None
    app.run(host='0.0.0.0', port=port, debug=debug)


