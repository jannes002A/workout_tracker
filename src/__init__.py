import os

from flask import Flask

from src.models import db

DEV_SECRET_KEY = "dev"  # stand-in for `python main.py` and the tests only


def create_app(test_config: dict | None = None) -> Flask:
    """Application factory. Pass a test_config dict to override settings."""
    app = Flask(__name__)
    production = _is_production()
    app.config.from_mapping(
        SECRET_KEY=_secret_key(production),
        SQLALCHEMY_DATABASE_URI="sqlite:///"
        + os.path.join(app.instance_path, "workouts.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # The session cookie only ever carries flash messages, but there is no
        # reason for a script to read it or for another site to send it.
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Off by default, because a cookie marked Secure is dropped over plain
        # HTTP and the flash messages would silently stop appearing. Turn it on
        # once the app is actually served over HTTPS.
        SESSION_COOKIE_SECURE=_flag("SESSION_COOKIE_SECURE"),
    )
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    with app.app_context():
        db.create_all()
        # A fresh database starts with the four sorts of sport; one that has
        # them (or extra ones added on the create page) is left alone.
        from src.services import ensure_categories

        ensure_categories()

    from src.routes import bp

    app.register_blueprint(bp)
    return app


def _is_production() -> bool:
    """Whether the app is being served for real, from APP_ENV.

    The container sets it; `python main.py` and the tests do not, so neither
    has to carry a SECRET_KEY around to keep working.
    """
    return os.environ.get("APP_ENV", "").strip().lower() == "production"


def _secret_key(production: bool) -> str:
    """The key the session cookie is signed with.

    Flash messages ride in that cookie, so anyone who knows the key can forge
    one — which is why a real deployment has to bring its own rather than
    inherit the dev stand-in baked into the source. In production an unset key,
    or the dev one, is fatal at startup instead of quietly insecure.
    """
    key = os.environ.get("SECRET_KEY", "").strip()
    if key and key != DEV_SECRET_KEY:
        return key
    if production:
        raise RuntimeError(
            "SECRET_KEY must be set to a secret of your own when "
            "APP_ENV=production: it signs the session cookie. Generate one "
            'with `python -c "import secrets; print(secrets.token_hex(32))"`.'
        )
    return DEV_SECRET_KEY


def _flag(name: str) -> bool:
    """Read a boolean environment variable. Anything unset or odd is False."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
