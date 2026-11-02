import os
import pytest

os.environ.setdefault("DATABASE_PATH", "/tmp/monday-briefing-test-bootstrap.sqlite3")
os.environ.setdefault("BRIEFING_PASSWORD", "testing-password")
os.environ.setdefault("SECRET_KEY", "testing-secret")

from app import LOGIN_FAILURES, OPEN_TRIGGERED, create_app


@pytest.fixture
def app(tmp_path):
    LOGIN_FAILURES.clear(); OPEN_TRIGGERED.clear()
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3"),
                      "BRIEFING_PASSWORD": "correct horse battery", "SECRET_KEY": "test-secret",
                      "BRIEFING_PUBLIC": False, "BRIEFING_SCHEDULE": False})
    return app


@pytest.fixture
def client(app): return app.test_client()


@pytest.fixture
def authed(client):
    client.post("/login", data={"password":"correct horse battery"})
    return client

