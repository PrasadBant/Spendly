import os
import tempfile

import pytest

import database.db as db
from app import app as flask_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Flask app configured to use an isolated, temporary SQLite DB file.

    We monkeypatch database.db.DB_PATH (a module-level constant used by
    get_db()) rather than app.config['DATABASE'], since that's the actual
    mechanism app.py/db.py use to locate the database file. This keeps
    tests from ever touching the real expense_tracker.db.
    """
    test_db_path = tmp_path / "test_expense_tracker.db"
    monkeypatch.setattr(db, "DB_PATH", str(test_db_path))

    flask_app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
    })

    with flask_app.app_context():
        db.init_db()
        # Intentionally do NOT call seed_db() here — tests create their own
        # deterministic fixture data so assertions aren't coupled to demo data.

    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def registered_user(app):
    """Create a user directly via db helpers and return (user_id, email, password)."""
    email = "profiletest@example.com"
    password = "testpass123"
    user_id = db.create_user("Test User", email, password)
    return {"id": user_id, "email": email, "password": password}


@pytest.fixture
def auth_client(client, registered_user):
    """A test client logged in as `registered_user`."""
    client.post(
        "/login",
        data={"email": registered_user["email"], "password": registered_user["password"]},
    )
    return client
