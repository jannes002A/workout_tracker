import os

from flask import Flask

from src.models import db


def create_app(test_config: dict | None = None) -> Flask:
    """Application factory. Pass a test_config dict to override settings."""
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY="dev",
        SQLALCHEMY_DATABASE_URI="sqlite:///"
        + os.path.join(app.instance_path, "workouts.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    with app.app_context():
        db.create_all()

    from src.routes import bp

    app.register_blueprint(bp)
    return app
