"""tests/test_cli_selfreload.py — TDD for `rawos selfreload arm-and-go` CLI
(Phase 25 Stage 1c: in-process self-reload trigger).

`arm-and-go` must POST to the in-process /internal/self-reload/arm-and-go
endpoint instead of calling execute_owner_self_reload (and os._exit) in the
CLI's own process. The CLI process is not rawos.service's MainPID, so
systemd would never respawn rawos against new_sha if the CLI process exits.
"""
from __future__ import annotations

import httpx
import pytest
from click.testing import CliRunner

from rawos.cli.main import cli


def _runner():
    return CliRunner()


class _Resp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_success_reports_armed(monkeypatch):
    captured = {}

    def _fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _Resp(200, {"status": "armed"})

    monkeypatch.setattr("httpx.post", _fake_post)
    result = _runner().invoke(cli, ["selfreload", "arm-and-go", "deadbeef", "--yes"])
    assert result.exit_code == 0
    assert "armed" in result.output.lower()
    assert captured["url"].endswith("/internal/self-reload/arm-and-go")
    assert captured["json"] == {"new_sha": "deadbeef"}


def test_transport_error_treated_as_success(monkeypatch):
    """The worker process dies mid-response on a real swap -- the HTTP
    connection drops. That is the expected SUCCESS signal, not an error."""

    def _fake_post(url, json=None, timeout=None):
        raise httpx.RemoteProtocolError("peer closed connection")

    monkeypatch.setattr("httpx.post", _fake_post)
    result = _runner().invoke(cli, ["selfreload", "arm-and-go", "deadbeef", "--yes"])
    assert result.exit_code == 0
    assert "armed" in result.output.lower() or "exit" in result.output.lower()


def test_refused_409_exits_nonzero(monkeypatch):
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **k: _Resp(409, {"detail": "refused: a self-reload is already pending"}),
    )
    result = _runner().invoke(cli, ["selfreload", "arm-and-go", "deadbeef", "--yes"])
    assert result.exit_code == 1
    assert "already pending" in result.output


def test_requires_confirmation_without_yes(monkeypatch):
    calls = []
    monkeypatch.setattr("httpx.post", lambda *a, **k: calls.append(1))
    result = _runner().invoke(cli, ["selfreload", "arm-and-go", "deadbeef"], input="n\n")
    assert result.exit_code != 0
    assert calls == []
