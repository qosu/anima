"""Auth + full API integration tests."""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile
import os

# Point to temp DB before importing app
os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.db")
os.environ["WORKSPACES_ROOT"] = str(Path(tempfile.mkdtemp()))
os.environ["JWT_SECRET"] = "test_secret_32chars_minimum_ok"
os.environ["DEEPSEEK_KEY"] = "test_key"

from rawos.api.app import app
import rawos.db as db

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    os.environ["DB_PATH"] = str(tmp_path / "test.db")
    os.environ["WORKSPACES_ROOT"] = str(tmp_path / "ws")
    db.init(os.environ["DB_PATH"])
    yield


class TestHealth:
    @pytest.mark.self_reload_smoke
    def test_health_ok(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestSignup:
    def test_signup_ok(self):
        r = client.post("/auth/signup", json={"email": "user@test.com", "password": "password123"})
        assert r.status_code == 201
        data = r.json()
        assert "access_token" in data
        assert "refresh_token" in data

    def test_signup_duplicate_email(self):
        client.post("/auth/signup", json={"email": "dup@test.com", "password": "password123"})
        r = client.post("/auth/signup", json={"email": "dup@test.com", "password": "password123"})
        assert r.status_code == 400
        assert "already registered" in r.json()["detail"]

    def test_signup_short_password(self):
        r = client.post("/auth/signup", json={"email": "x@test.com", "password": "short"})
        assert r.status_code == 400

    def test_signup_invalid_email(self):
        r = client.post("/auth/signup", json={"email": "notanemail", "password": "password123"})
        assert r.status_code in (400, 422)


class TestLogin:
    def test_login_ok(self):
        client.post("/auth/signup", json={"email": "login@test.com", "password": "password123"})
        r = client.post("/auth/login", json={"email": "login@test.com", "password": "password123"})
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_login_wrong_password(self):
        client.post("/auth/signup", json={"email": "wrong@test.com", "password": "password123"})
        r = client.post("/auth/login", json={"email": "wrong@test.com", "password": "wrongpass"})
        assert r.status_code == 401

    def test_login_unknown_email(self):
        r = client.post("/auth/login", json={"email": "ghost@test.com", "password": "password123"})
        assert r.status_code == 401


class TestMe:
    def test_me_authenticated(self):
        r = client.post("/auth/signup", json={"email": "me@test.com", "password": "password123"})
        token = r.json()["access_token"]
        r2 = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200
        data = r2.json()
        assert data["email"] == "me@test.com"
        assert "password_hash" not in data

    def test_me_unauthenticated(self):
        r = client.get("/auth/me")
        assert r.status_code == 401

    def test_me_invalid_token(self):
        r = client.get("/auth/me", headers={"Authorization": "Bearer invalidtoken"})
        assert r.status_code == 401


class TestRefresh:
    def test_refresh_ok(self):
        r = client.post("/auth/signup", json={"email": "ref@test.com", "password": "password123"})
        refresh = r.json()["refresh_token"]
        r2 = client.post("/auth/refresh", json={"refresh_token": refresh})
        assert r2.status_code == 200
        assert "access_token" in r2.json()

    def test_refresh_invalid(self):
        r = client.post("/auth/refresh", json={"refresh_token": "badtoken"})
        assert r.status_code == 401

    def test_refresh_single_use(self):
        r = client.post("/auth/signup", json={"email": "su@test.com", "password": "password123"})
        refresh = r.json()["refresh_token"]
        client.post("/auth/refresh", json={"refresh_token": refresh})
        r2 = client.post("/auth/refresh", json={"refresh_token": refresh})
        assert r2.status_code == 401


class TestProjects:
    def _auth_header(self, email="proj@test.com"):
        r = client.post("/auth/signup", json={"email": email, "password": "password123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def test_create_project(self):
        headers = self._auth_header()
        r = client.post("/projects", json={"name": "My App"}, headers=headers)
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "My App"
        assert data["workdir"] != ""

    def test_list_projects(self):
        headers = self._auth_header("list@test.com")
        client.post("/projects", json={"name": "P1"}, headers=headers)
        client.post("/projects", json={"name": "P2"}, headers=headers)
        r = client.get("/projects", headers=headers)
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_project_isolation(self):
        h1 = self._auth_header("u1@test.com")
        h2 = self._auth_header("u2@test.com")
        r = client.post("/projects", json={"name": "Secret"}, headers=h1)
        pid = r.json()["id"]
        r2 = client.get(f"/projects/{pid}", headers=h2)
        assert r2.status_code == 404

    def test_unauthenticated_blocked(self):
        r = client.post("/projects", json={"name": "X"})
        assert r.status_code == 401
