import os
import secrets
from pathlib import Path

import click
from flask import Flask, render_template, session
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "site.login"


def create_app(test_config=None):
    app = Flask(__name__)
    instance_path = Path(app.instance_path)
    instance_path.mkdir(parents=True, exist_ok=True)

    database_url = os.environ.get("DATABASE_URL")
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    if database_url and database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        SQLALCHEMY_DATABASE_URI=database_url or f"sqlite:///{instance_path / 'rallylog.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("APP_ENV") == "production",
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    login_manager.init_app(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id)) if user_id.isdigit() else None

    @app.context_processor
    def csrf_context():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return {"csrf_token": session["csrf_token"]}

    from .routes import site

    app.register_blueprint(site)

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(500)
    def friendly_error(error):
        return render_template("error.html", code=error.code), error.code

    @app.cli.command("import-tennis")
    @click.option("--from-year", default=2023, type=int, show_default=True)
    @click.option("--to-year", default=2026, type=int, show_default=True)
    def import_tennis(from_year, to_year):
        """Import ATP and WTA results from the Sackmann archive."""
        from .importer import import_archive

        if from_year > to_year or from_year < 1968 or to_year > 2026:
            raise click.BadParameter("Choose a year range from 1968 through 2026.")
        count = import_archive(from_year, to_year)
        click.echo(f"Imported {count} new matches.")

    with app.app_context():
        db.create_all()
        from .importer import seed_samples

        seed_samples()

    return app
