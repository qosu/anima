"""
Stage 3 — _update_earned_autonomy_track_records: observational wiring of
the earned-autonomy ladder into _run_autonomous_scan.

For every (repo_root, anomaly_domain) rawos has previously proposed a
rawos/fix-* branch for (rawos_commits.repo_root/anomaly_domain), check
whether a human has merged that branch (is_branch_merged) and whether the
anomaly is currently present in the latest scan snapshot, then advance
that class's autonomy_track_record accordingly. Read-only with respect to
the scanned repos.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile

import pytest

import rawos.db as db
from rawos.context.server_scanner import ServerAnomaly, ServerStateSnapshot
from rawos.kernel.track_record import get_track_record
from rawos.models import User
from rawos.scheduler.proactive import (
    RAWOS_ENTITY_USER_ID,
    _update_earned_autonomy_track_records,
)


def _git(*args: str, cwd: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _git_out(*args: str, cwd: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def origin_and_clone(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git("init", "-q", "-b", "main", cwd=str(origin))
    _git("config", "user.email", "test@rawos.local", cwd=str(origin))
    _git("config", "user.name", "rawos-test", cwd=str(origin))
    _git("config", "receive.denyCurrentBranch", "updateInstead", cwd=str(origin))
    (origin / "README.md").write_text("init\n")
    _git("add", ".", cwd=str(origin))
    _git("commit", "-q", "-m", "init", cwd=str(origin))

    clone = tmp_path / "clone"
    _git("clone", "-q", str(origin), str(clone), cwd=str(tmp_path))
    _git("config", "user.email", "test@rawos.local", cwd=str(clone))
    _git("config", "user.name", "rawos-test", cwd=str(clone))
    return origin, clone


def _record_fix_commit(user_id: str, repo_root: str, anomaly_domain: str, branch: str, sha: str) -> None:
    with db._conn() as conn:
        conn.execute(
            "INSERT INTO rawos_commits "
            "(user_id, project_id, branch, commit_hash, message, workdir, repo_root, anomaly_domain) "
            "VALUES (?, NULL, ?, ?, 'rawos: autonomous fix', '/root/.rawos-worktrees/x', ?, ?)",
            (user_id, branch, sha, repo_root, anomaly_domain),
        )


class TestUpdateEarnedAutonomyTrackRecords:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        db.init(os.path.join(self.tmp, "test.db"))
        db.create_user(User(
            id=RAWOS_ENTITY_USER_ID,
            email=f"rawos-entity-{id(self)}@test.com",
            password_hash=hashlib.sha256(b"pass").hexdigest(),
        ))

    @pytest.mark.asyncio
    async def test_unmerged_branch_does_not_advance_track_record(self, origin_and_clone):
        origin, clone = origin_and_clone
        _git("checkout", "-q", "-b", "rawos/fix-x", cwd=str(clone))
        (clone / "fix.txt").write_text("fix\n")
        _git("add", "fix.txt", cwd=str(clone))
        _git("commit", "-q", "-m", "rawos: fix x", cwd=str(clone))
        sha = _git_out("rev-parse", "HEAD", cwd=str(clone))

        domain = "service_failed:foo.service"
        _record_fix_commit(RAWOS_ENTITY_USER_ID, str(clone), domain, "rawos/fix-x", sha)

        snapshot = ServerStateSnapshot(ts=0, anomalies=[])
        await _update_earned_autonomy_track_records(snapshot)

        state = get_track_record(RAWOS_ENTITY_USER_ID, str(clone), domain)
        assert state.verified_successes == 0
        assert state.last_fix_branch is None

    @pytest.mark.asyncio
    async def test_merged_and_resolved_starts_then_completes_stability_window(self, origin_and_clone):
        origin, clone = origin_and_clone
        _git("checkout", "-q", "-b", "rawos/fix-x", cwd=str(clone))
        (clone / "fix.txt").write_text("fix\n")
        _git("add", "fix.txt", cwd=str(clone))
        _git("commit", "-q", "-m", "rawos: fix x", cwd=str(clone))
        sha = _git_out("rev-parse", "HEAD", cwd=str(clone))

        # Simulate a human merging the fix into origin's default branch.
        _git("push", "-q", "origin", "rawos/fix-x", cwd=str(clone))
        _git("checkout", "-q", "main", cwd=str(clone))
        _git("merge", "-q", "--no-ff", "-m", "merge fix", "rawos/fix-x", cwd=str(clone))
        _git("push", "-q", "origin", "main", cwd=str(clone))
        _git("fetch", "-q", "origin", cwd=str(clone))

        # repo_root is the working clone (has an `origin` remote, like the
        # real liveproof-agent checkout) — not the bare-ish "GitHub" repo.
        domain = "service_failed:foo.service"
        _record_fix_commit(RAWOS_ENTITY_USER_ID, str(clone), domain, "rawos/fix-x", sha)

        # Cycle 1: anomaly absent (resolved) — starts the stability window.
        snapshot = ServerStateSnapshot(ts=0, anomalies=[])
        await _update_earned_autonomy_track_records(snapshot)
        state = get_track_record(RAWOS_ENTITY_USER_ID, str(clone), domain)
        assert state.verified_successes == 0
        assert state.pending_since is not None
        assert state.last_outcome == "merged_pending_stability"

        # Cycle 2: still absent — confirms stability, +1 verified success.
        await _update_earned_autonomy_track_records(snapshot)
        state = get_track_record(RAWOS_ENTITY_USER_ID, str(clone), domain)
        assert state.verified_successes == 1
        assert state.pending_since is None
        assert state.last_outcome == "merged_resolved"

    @pytest.mark.asyncio
    async def test_merged_but_anomaly_still_present_records_regression(self, origin_and_clone):
        origin, clone = origin_and_clone
        _git("checkout", "-q", "-b", "rawos/fix-x", cwd=str(clone))
        (clone / "fix.txt").write_text("fix\n")
        _git("add", "fix.txt", cwd=str(clone))
        _git("commit", "-q", "-m", "rawos: fix x", cwd=str(clone))
        sha = _git_out("rev-parse", "HEAD", cwd=str(clone))

        _git("push", "-q", "origin", "rawos/fix-x", cwd=str(clone))
        _git("checkout", "-q", "main", cwd=str(clone))
        _git("merge", "-q", "--no-ff", "-m", "merge fix", "rawos/fix-x", cwd=str(clone))
        _git("push", "-q", "origin", "main", cwd=str(clone))
        _git("fetch", "-q", "origin", cwd=str(clone))

        domain = "service_failed:foo.service"
        _record_fix_commit(RAWOS_ENTITY_USER_ID, str(clone), domain, "rawos/fix-x", sha)

        snapshot = ServerStateSnapshot(
            ts=0,
            anomalies=[ServerAnomaly(
                kind="service_failed", affected_path=str(clone),
                service="foo.service", detail="still failing", last_log="",
                severity=8,
            )],
        )
        await _update_earned_autonomy_track_records(snapshot)

        state = get_track_record(RAWOS_ENTITY_USER_ID, str(clone), domain)
        assert state.verified_successes == 0
        assert state.last_outcome == "merged_regressed"
        assert state.pending_since is None
