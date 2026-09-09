import pytest

from src import create_app, services
from src.models import db


@pytest.fixture()
def app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def user(app):
    """The default person sessions are logged against."""
    return services.create_user("Alex", 34)


@pytest.fixture()
def other_user(app):
    """A second person, for the tests that check the analytics are separated."""
    return services.create_user("Sam", 41)


@pytest.fixture()
def client(app):
    return app.test_client()
