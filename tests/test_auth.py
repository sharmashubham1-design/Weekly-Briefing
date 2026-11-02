import pytest
from app import create_app


def test_auth_gates_pages_and_api(client):
    assert client.get("/").status_code == 302
    assert client.get("/api/bootstrap").status_code == 401
    assert client.get("/healthz").status_code == 200
    assert client.post("/login", data={"password":"correct horse battery"}).status_code == 302
    assert client.get("/api/bootstrap").status_code == 200


def test_lockout_after_five_failures(client):
    for _ in range(5): assert client.post("/login", data={"password":"wrong"}).status_code == 200
    response = client.post("/login", data={"password":"correct horse battery"})
    assert response.status_code == 200
    assert b"Too many attempts" in response.data


def test_refuses_short_public_password(tmp_path):
    with pytest.raises(RuntimeError, match="at least 10"):
        create_app({"TESTING":True,"DATABASE":str(tmp_path/"x.db"),"BRIEFING_PUBLIC":True,
                    "BRIEFING_PASSWORD":"short","SECRET_KEY":"strong-secret"})


def test_refuses_default_public_secret(tmp_path):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app({"TESTING":True,"DATABASE":str(tmp_path/"x.db"),"BRIEFING_PUBLIC":True,
                    "BRIEFING_PASSWORD":"long-enough-password","SECRET_KEY":"dev-only-change-me"})

