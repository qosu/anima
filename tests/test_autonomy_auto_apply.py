"""
Stage 3 — _maybe_auto_apply: the final gate before reversible_apply runs.

A (repo, anomaly_domain) class only gets auto-applied when ALL of:
  1. settings.autonomy_auto_apply_enabled is True (operator opt-in, default False)
  2. its autonomy_track_record has graduated (>=3 verified human-merged
     successes, see kernel.track_record)
  3. the proposed fix's diff is <= AUTO_APPLY_MAX_DIFF_LINES
  4. the anomaly has a systemd service to restart (anomaly.service non-empty)

reversible_apply itself is fully tested in test_reversible_apply*.py — here
we only test the gating decision, so reversible_apply is monkeypatched to a
stub that records its call args.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile

import pytest

import anima.db as db
from anima.context.server_scanner import ServerAnomaly
from anima.kernel.reversible_apply import ApplyResult
from anima.kernel.track_record import update_track_record
from anima.models import User
from anima.scheduler import proactive
from anima.scheduler.proactive import (
    AUTO_APPLY_MAX_DIFF_LINES,
    RAWOS_ENTITY_USER_ID,
    _maybe_auto_apply,
    _parse_diff_shortstat_total,
)


def _git(*args: str, cwd: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _git_out(*args: str, cwd: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.mark.parametrize("shortstat,expected", [
    ("", 0),
    (" 1 file changed, 1 insertion(+)\n", 1),
    (" 2 files changed, 10 insertions(+), 3 deletions(-)\n", 13),
    (" 3 files changed, 7 deletions(-)\n", 7),
])
def test_parse_diff_shortstat_total(shortstat, expected):
    assert _parse_diff_shortstat_total(shortstat) == expected


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git("init", "-q", "-b", "main", cwd=str(root))
    _git("config", "user.email", "test@rawos.local", cwd=str(root))
    _git("config", "user.name", "rawos-test", cwd=str(root))
    (root / "app.txt").write_text("v1\n")
    _git("add", ".", cwd=str(root))
    _git("commit", "-q", "-m", "init", cwd=str(root))
    return root


def _graduate(repo_root: str, domain: str) -> None:
    for cycle, branch in enumerate(["rawos/fix-1", "rawos/fix-2", "rawos/fix-3"]):
        update_track_record(
            RAWOS_ENTITY_USER_ID, repo_root, domain,
            anomaly_present=False, branch_merged=True,
            fix_branch=branch, fix_sha=branch, now=cycle * 1000,
        )
        update_track_record(
            RAWOS_ENTITY_USER_ID, repo_root, domain,
            anomaly_present=False, branch_merged=True,
            fix_branch=branch, fix_sha=branch, now=cycle * 1000 + 500,
        )


def _anomaly(repo_root: str, service: str = "foo.service") -> ServerAnomaly:
    return ServerAnomaly(
        kind="service_failed", affected_path=repo_root, service=service,
        detail="d", last_log="", severity=8,
    )


@pytest.mark.asyncio
class TestMaybeAutoApply:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        db.init(os.path.join(self.tmp, "test.db"))
        db.create_user(User(
            id=RAWOS_ENTITY_USER_ID,
            email=f"rawos-entity-{id(self)}@test.com",
            password_hash=hashlib.sha256(b"pass").hexdigest(),
        ))

    def _make_fix_branch(self, repo) -> str:
        _git("checkout", "-q", "-b", "rawos/fix-x", cwd=str(repo))
        (repo / "app.txt").write_text("v2\n")
        _git("add", "app.txt", cwd=str(repo))
        _git("commit", "-q", "-m", "rawos: fix x", cwd=str(repo))
        _git("checkout", "-q", "main", cwd=str(repo))
        return "rawos/fix-x"

    async def test_disabled_by_default_returns_none(self, repo, monkeypatch):
        monkeypatch.setattr(proactive.settings, "autonomy_auto_apply_enabled", False)
        domain = "service_failed:foo.service"
        _graduate(str(repo), domain)
        base_sha = _git_out("rev-parse", "HEAD", cwd=str(repo))
        fix_branch = self._make_fix_branch(repo)

        result = await _maybe_auto_apply(_anomaly(str(repo)), {"repo_root": str(repo)}, fix_branch, base_sha)

        assert result is None

    async def test_not_graduated_returns_none(self, repo, monkeypatch):
        monkeypatch.setattr(proactive.settings, "autonomy_auto_apply_enabled", True)
        base_sha = _git_out("rev-parse", "HEAD", cwd=str(repo))
        fix_branch = self._make_fix_branch(repo)

        result = await _maybe_auto_apply(_anomaly(str(repo)), {"repo_root": str(repo)}, fix_branch, base_sha)

        assert result is None

    async def test_diff_exceeding_cap_returns_none(self, repo, monkeypatch):
        monkeypatch.setattr(proactive.settings, "autonomy_auto_apply_enabled", True)
        domain = "service_failed:foo.service"
        _graduate(str(repo), domain)
        base_sha = _git_out("rev-parse", "HEAD", cwd=str(repo))

        _git("checkout", "-q", "-b", "rawos/fix-big", cwd=str(repo))
        (repo / "app.txt").write_text("\n".join(f"line {i}" for i in range(AUTO_APPLY_MAX_DIFF_LINES + 10)) + "\n")
        _git("add", "app.txt", cwd=str(repo))
        _git("commit", "-q", "-m", "rawos: huge fix", cwd=str(repo))
        _git("checkout", "-q", "main", cwd=str(repo))

        result = await _maybe_auto_apply(_anomaly(str(repo)), {"repo_root": str(repo)}, "rawos/fix-big", base_sha)

        assert result is None

    async def test_no_service_returns_none(self, repo, monkeypatch):
        monkeypatch.setattr(proactive.settings, "autonomy_auto_apply_enabled", True)
        domain = "disk_critical"
        _graduate(str(repo), domain)
        base_sha = _git_out("rev-parse", "HEAD", cwd=str(repo))
        fix_branch = self._make_fix_branch(repo)

        anomaly = ServerAnomaly(
            kind="disk_critical", affected_path=str(repo), service="",
            detail="d", last_log="", severity=9,
        )
        result = await _maybe_auto_apply(anomaly, {"repo_root": str(repo)}, fix_branch, base_sha)

        assert result is None

    async def test_all_gates_pass_calls_reversible_apply(self, repo, monkeypatch):
        monkeypatch.setattr(proactive.settings, "autonomy_auto_apply_enabled", True)
        domain = "service_failed:foo.service"
        _graduate(str(repo), domain)
        base_sha = _git_out("rev-parse", "HEAD", cwd=str(repo))
        fix_branch = self._make_fix_branch(repo)

        captured = {}
        sentinel = ApplyResult(True, True, False, base_sha, "deadbeef", "ok")

        async def fake_reversible_apply(repo_root, branch, service_name, *, health_check, **kw):
            captured["repo_root"] = repo_root
            captured["branch"] = branch
            captured["service_name"] = service_name
            captured["health_check"] = health_check
            return sentinel

        monkeypatch.setattr(proactive, "reversible_apply", fake_reversible_apply)

        result = await _maybe_auto_apply(_anomaly(str(repo)), {"repo_root": str(repo)}, fix_branch, base_sha)

        assert result is sentinel
        assert captured["repo_root"] == str(repo)
        assert captured["branch"] == fix_branch
        assert captured["service_name"] == "foo.service"
        assert callable(captured["health_check"])
