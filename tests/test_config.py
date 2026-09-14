"""The settings `create_app` reads from the environment.

These matter to the container more than to `python main.py`: APP_ENV is what
tells the app it is being served for real, and the dev SECRET_KEY baked into
the source must not survive into a deployment.
"""

import pytest

from src import DEV_SECRET_KEY, create_app


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start every test from an environment that sets none of these."""
    for name in ("APP_ENV", "SECRET_KEY", "SESSION_COOKIE_SECURE"):
        monkeypatch.delenv(name, raising=False)


def memory(**extra) -> dict:
    """A test_config that keeps the database out of the real instance folder."""
    return {"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True, **extra}


# ------------------------------------------------------------- the secret key


def test_development_falls_back_to_the_dev_secret_key(monkeypatch):
    """No APP_ENV, so `python main.py` and pytest keep working unchanged."""
    app = create_app(memory())
    assert app.config["SECRET_KEY"] == DEV_SECRET_KEY


def test_secret_key_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a-real-one")
    app = create_app(memory())
    assert app.config["SECRET_KEY"] == "a-real-one"


def test_production_without_a_secret_key_refuses_to_start(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="SECRET_KEY must be set"):
        create_app(memory())


def test_production_rejects_the_dev_secret_key(monkeypatch):
    """Setting it to the source's own stand-in is no better than not setting it."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", DEV_SECRET_KEY)
    with pytest.raises(RuntimeError, match="SECRET_KEY must be set"):
        create_app(memory())


def test_production_rejects_a_blank_secret_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "   ")
    with pytest.raises(RuntimeError, match="SECRET_KEY must be set"):
        create_app(memory())


def test_production_with_a_secret_key_starts(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "0123456789abcdef")
    app = create_app(memory())
    assert app.config["SECRET_KEY"] == "0123456789abcdef"


@pytest.mark.parametrize("value", ["", "development", "prod", "Production "])
def test_only_the_exact_word_production_is_production(monkeypatch, value):
    """Anything else is a development run, which needs no secret of its own.

    'Production ' is the one that must still count — APP_ENV is compared
    case-insensitively and stripped, so a stray space cannot silently turn the
    check off.
    """
    monkeypatch.setenv("APP_ENV", value)
    if value.strip().lower() == "production":
        with pytest.raises(RuntimeError):
            create_app(memory())
    else:
        assert create_app(memory()).config["SECRET_KEY"] == DEV_SECRET_KEY


# ------------------------------------------------------------ cookie settings


def test_session_cookie_is_locked_down_by_default():
    app = create_app(memory())
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_session_cookie_secure_is_off_unless_asked_for():
    """A Secure cookie is dropped over plain HTTP, taking the flashes with it."""
    assert create_app(memory()).config["SESSION_COOKIE_SECURE"] is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_session_cookie_secure_can_be_turned_on(monkeypatch, value):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", value)
    assert create_app(memory()).config["SESSION_COOKIE_SECURE"] is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "maybe"])
def test_session_cookie_secure_ignores_anything_else(monkeypatch, value):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", value)
    assert create_app(memory()).config["SESSION_COOKIE_SECURE"] is False
