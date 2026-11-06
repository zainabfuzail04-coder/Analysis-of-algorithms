"""Hotel Management System - application factory (entry point)."""
import os
from flask import Flask
from sqlalchemy import inspect, text
from models import db
from views import bp


def add_missing_columns():
    """create_all() purani table mein naye columns nahi jorta. Ye helper unhe ALTER TABLE se jor deta hai,
    taake purani hotel.db delete kiye baghair project chalta rahe."""
    insp, prep = inspect(db.engine), db.engine.dialect.identifier_preparer
    for t in db.metadata.tables.values():
        if not insp.has_table(t.name):
            continue
        have = {c["name"] for c in insp.get_columns(t.name)}
        for c in t.columns:
            if c.name not in have:
                typ = c.type.compile(dialect=db.engine.dialect)
                db.session.execute(text(f"ALTER TABLE {prep.quote(t.name)} ADD COLUMN {prep.quote(c.name)} {typ}"))
    db.session.commit()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///hotel.db")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"          # cross-site POST (CSRF) se bachao
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("HTTPS") == "1"
    if app.config["SECRET_KEY"] == "dev-secret-change-me":
        print("WARNING: SECRET_KEY set nahi hai - deploy karne se pehle zaroor set karein.")
    db.init_app(app)
    app.register_blueprint(bp)
    with app.app_context():
        db.create_all()          # saari 41 tables ban jati hain
        add_missing_columns()
    return app


if __name__ == "__main__":
    create_app().run(debug=os.environ.get("FLASK_DEBUG", "1") == "1")
