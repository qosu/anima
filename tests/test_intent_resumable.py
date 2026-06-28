"""
tests/test_intent_resumable.py — Stage F: resumable /intent conversation protocol.

Covers the FastAPI-level behavior introduced in Stage F:
  - orchestration finalization (billing, intent status) is connection-
    independent (the core defect fix);
  - the SSE stream is framed with a leading `run_started` and a terminal
    `run_complete` control event;
  - `GET /intent/{run_id}/stream` replays buffered events after a given
    `Last-Event-ID` for reconnect;
  - reconnect is scoped to the owning user and to known/live runs.

`orchestrator.run` is patched with a small async-generator stub so these
tests are independent of the real agent/LLM pipeline.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.db")
os.environ["WORKSPACES_ROOT"] = str(Path(tempfile.mkdtemp()))
os.environ["JWT_SECRET"] = "test_secret_32chars_minimum_ok"
os.environ["DEEPSEEK_KEY"] = "test_key"

from anima.api.app import app
from anima.api import intent_routes
from anima.config import settings
import anima.db as db


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    ws_root = str(tmp_path / "ws")
    os.environ["DB_PATH"] = db_path
    os.environ["WORKSPACES_ROOT"] = ws_root
    # `with TestClient(app) as client:` runs the app's lifespan, which calls
    # `db.init(settings.db_path)` — that would override our per-test db.init
    # below with the (process-wide, possibly real) `settings.db_path` unless
    # we also point the cached `settings` singleton at this test's tmp_path.
    monkeypatch.setattr(settings, "db_path", db_path)
    monkeypatch.setattr(settings, "workspaces_root", ws_root)
    db.init(db_path)
    yield


def _signup_and_create_project(client, email: str = "resumable@example.com"):
    r = client.post("/auth/signup", json={"email": email, "password": "password123"})
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post("/projects", json={"name": "My App"}, headers=headers)
    project_id = r.json()["id"]
    return headers, project_id


async def _mock_orchestrator_run(**kwargs):
    yield {"type": "chunk", "text": "hello "}
    yield {"type": "chunk", "text": "world"}
    yield {"type": "done", "intent_id": kwargs.get("intent_id", ""), "agent_id": ""}


def _parse_sse_frames(lines: list[str]) -> list[tuple[int | None, dict]]:
    """Parse raw SSE lines into [(seq_from_id_line_or_None, event_dict), ...]."""
    frames: list[tuple[int | None, dict]] = []
    pending_id: int | None = None
    for line in lines:
        if not line:
            continue
        if line.startswith("id: "):
            pending_id = int(line[len("id: "):].strip())
            continue
        if line.startswith("event: "):
            continue
        if line.startswith("data: "):
            frames.append((pending_id, json.loads(line[len("data: "):])))
            pending_id = None
    return frames


# ---------------------------------------------------------------------------
# 9. Core defect fix: finalization is connection-independent
# ---------------------------------------------------------------------------

class TestFinalizationConnectionIndependent:
    def test_finalization_completes_after_client_disconnects(self):
        with TestClient(app) as client:
            headers, project_id = _signup_and_create_project(client)

            with patch.object(intent_routes.orchestrator, "run", side_effect=_mock_orchestrator_run):
                with client.stream(
                    "POST", "/intent",
                    json={"project_id": project_id, "message": "hi"},
                    headers=headers,
                ) as resp:
                    assert resp.status_code == 200
                    run_id = None
                    for line in resp.iter_lines():
                        if line.startswith("data: "):
                            event = json.loads(line[len("data: "):])
                            if event.get("type") == "run_started":
                                run_id = event["run_id"]
                            break  # disconnect after the very first event

            assert run_id is not None

            # Background orchestration must finish even though the client
            # already disconnected.
            history = []
            for _ in range(50):
                history = db.get_project_history(_user_id(client, headers), project_id)
                matching = [i for i in history if i.id == run_id]
                if matching and matching[0].status.value == "completed":
                    break
                time.sleep(0.05)

            matching = [i for i in history if i.id == run_id]
            assert matching, "intent not found in history"
            assert matching[0].status.value == "completed"

            user = db.get_user_by_id(_user_id(client, headers))
            assert user.tokens_used_today > 0


def _user_id(client, headers) -> str:
    r = client.get("/auth/me", headers=headers)
    return r.json()["id"]


# ---------------------------------------------------------------------------
# 10. run_started / run_complete framing
# ---------------------------------------------------------------------------

class TestRunFraming:
    def test_stream_starts_with_run_started_and_ends_with_run_complete(self):
        with TestClient(app) as client:
            headers, project_id = _signup_and_create_project(client, "framing@example.com")

            with patch.object(intent_routes.orchestrator, "run", side_effect=_mock_orchestrator_run):
                with client.stream(
                    "POST", "/intent",
                    json={"project_id": project_id, "message": "hi"},
                    headers=headers,
                ) as resp:
                    assert resp.status_code == 200
                    lines = list(resp.iter_lines())

        frames = _parse_sse_frames(lines)
        assert frames[0][1]["type"] == "run_started"
        assert "run_id" in frames[0][1]
        assert frames[-1][1]["type"] == "run_complete"
        assert frames[-1][1]["status"] == "completed"


# ---------------------------------------------------------------------------
# 11. GET /intent/{run_id}/stream replay via Last-Event-ID
# ---------------------------------------------------------------------------

class TestReconnectReplay:
    def test_reconnect_replays_only_events_after_last_event_id(self):
        with TestClient(app) as client:
            headers, project_id = _signup_and_create_project(client, "replay@example.com")

            with patch.object(intent_routes.orchestrator, "run", side_effect=_mock_orchestrator_run):
                with client.stream(
                    "POST", "/intent",
                    json={"project_id": project_id, "message": "hi"},
                    headers=headers,
                ) as resp:
                    lines = list(resp.iter_lines())

        all_frames = _parse_sse_frames(lines)
        assert len(all_frames) >= 2
        run_id = all_frames[0][1]["run_id"]
        first_seq = all_frames[0][0]
        assert first_seq is not None

        with TestClient(app) as client:
            # second TestClient context creates a fresh portal but shares
            # the same on-disk db / in-process registry (module-level
            # singleton), so a fresh login as the same user is sufficient.
            r = client.post("/auth/login", json={"email": "replay@example.com", "password": "password123"})
            token = r.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            r = client.get(
                f"/intent/{run_id}/stream",
                headers={**headers, "Last-Event-ID": str(first_seq)},
            )
            assert r.status_code == 200
            replay_frames = _parse_sse_frames(r.text.splitlines())

        # Only events with seq > first_seq, ending with run_complete.
        assert all(seq is not None and seq > first_seq for seq, _ in replay_frames)
        assert replay_frames[-1][1]["type"] == "run_complete"
        assert len(replay_frames) == len(all_frames) - 1


# ---------------------------------------------------------------------------
# 12. Reconnect auth scoping
# ---------------------------------------------------------------------------

class TestReconnectAuthScoping:
    def test_unknown_run_id_returns_404(self):
        with TestClient(app) as client:
            headers, _ = _signup_and_create_project(client, "unknown-run@example.com")
            r = client.get("/intent/does-not-exist/stream", headers=headers)
            assert r.status_code == 404

    def test_other_users_run_returns_404(self):
        with TestClient(app) as client:
            headers_a, project_id_a = _signup_and_create_project(client, "owner@example.com")
            headers_b, _ = _signup_and_create_project(client, "intruder@example.com")

            with patch.object(intent_routes.orchestrator, "run", side_effect=_mock_orchestrator_run):
                with client.stream(
                    "POST", "/intent",
                    json={"project_id": project_id_a, "message": "hi"},
                    headers=headers_a,
                ) as resp:
                    lines = list(resp.iter_lines())

        frames = _parse_sse_frames(lines)
        run_id = frames[0][1]["run_id"]

        with TestClient(app) as client:
            r = client.post("/auth/login", json={"email": "intruder@example.com", "password": "password123"})
            token = r.json()["access_token"]
            headers_b = {"Authorization": f"Bearer {token}"}
            r = client.get(f"/intent/{run_id}/stream", headers=headers_b)
            assert r.status_code == 404
