"""CryzonCloud Cpanel - package init & application factory."""
import os
from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=[])


def create_app(config=None):
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        template_folder=os.path.join(base, "templates"),
        static_folder=os.path.join(base, "static"),
    )

    # ---- Secret key (persisted) ----
    secret_file = os.path.join(base, ".secret_key")
    if os.path.exists(secret_file):
        with open(secret_file) as f:
            app.secret_key = f.read().strip()
    else:
        app.secret_key = os.urandom(32).hex()
        try:
            with open(secret_file, "w") as f:
                f.write(app.secret_key)
        except OSError:
            pass

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 7,
        MAX_CONTENT_LENGTH=512 * 1024 * 1024,
        JSON_SORT_KEYS=False,
    )
    if config:
        app.config.update(config)

    limiter.init_app(app)

    from . import db
    db.init_app(app)

    from .routes import bp as main_bp
    app.register_blueprint(main_bp)

    from .routes_api import bp as api_bp
    app.register_blueprint(api_bp)

    from .routes_admin import bp as admin_bp
    app.register_blueprint(admin_bp)

    from .terminal import register_terminal_routes
    register_terminal_routes(app)

    @app.context_processor
    def inject_globals():
        from .security import current_user, has_permission, is_admin, PERMISSION_GROUPS
        u = current_user()
        return {
            "settings": db.get_settings(),
            "current_user": u,
            "can": (lambda p: has_permission(u, p)),
            "is_admin_user": is_admin(u),
            "permission_groups": PERMISSION_GROUPS,
        }

    # ---- Template filters ----
    @app.template_filter("duration")
    def _duration(seconds):
        try:
            seconds = int(seconds)
        except (TypeError, ValueError):
            return "—"
        if seconds <= 0:
            return "—"
        d, rem = divmod(seconds, 86400)
        h, rem = divmod(rem, 3600)
        m, _ = divmod(rem, 60)
        parts = []
        if d:
            parts.append(f"{d}d")
        if h:
            parts.append(f"{h}h")
        if m and not d:
            parts.append(f"{m}m")
        return " ".join(parts) or f"{seconds}s"

    @app.template_filter("dt")
    def _dt(value, fmt="%b %d, %Y %H:%M"):
        if not value:
            return "—"
        try:
            from datetime import datetime
            if isinstance(value, str):
                value = value.replace("Z", "").split(".")[0]
                value = datetime.fromisoformat(value)
            return value.strftime(fmt)
        except (ValueError, TypeError):
            return str(value)

    # Ensure schema, roles and the default owner account exist.
    db.init_db()

    return app
