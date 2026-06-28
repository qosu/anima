"""
Stage 3 — _record_git_commits records repo_root + anomaly_domain for
SERVER_SCAN commits, so _update_earned_autonomy_track_records can later
find the most recent rawos/fix-* branch proposed for a (repo, domain).
"""
from __future__ import annotations

import hashlib
import os
import tempfile

import anima.db as db
from anima.models import User
from anima.scheduler.proactive import _record_git_commits


class TestRecordGitCommitsRepoRoot:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        db.init(os.path.join(self.tmp, "test.db"))
        self.user = db.create_user(User(
            email=f"commits-{id(self)}@test.com",
            password_hash=hashlib.sha256(b"pass").hexdigest(),
        ))

    def _commit_event(self, output: str) -> list[dict]:
        return [{
            "type": "tool_result",
            "tool": "git_commit",
            "success": True,
            "output": output,
        }]

    def test_records_repo_root_and_anomaly_domain_for_server_scan(self):
        _record_git_commits(
            self.user.id, None, "/root/.rawos-worktrees/some-repo-123",
            self._commit_event("[rawos/fix-x abc1234] rawos: fix x"),
            repo_root="/root/some-repo",
            anomaly_domain="service_failed:foo.service",
        )
        with db._conn() as conn:
            row = conn.execute(
                "SELECT repo_root, anomaly_domain, branch, commit_hash, workdir "
                "FROM rawos_commits WHERE user_id = ?",
                (self.user.id,),
            ).fetchone()
        assert row["repo_root"] == "/root/some-repo"
        assert row["anomaly_domain"] == "service_failed:foo.service"
        assert row["branch"] == "rawos/fix-x"
        assert row["commit_hash"] == "abc1234"
        assert row["workdir"] == "/root/.rawos-worktrees/some-repo-123"

    def test_repo_root_and_anomaly_domain_default_to_none(self):
        _record_git_commits(
            self.user.id, None, "/root/some-workdir",
            self._commit_event("[main abc1234] some commit"),
        )
        with db._conn() as conn:
            row = conn.execute(
                "SELECT repo_root, anomaly_domain FROM rawos_commits WHERE user_id = ?",
                (self.user.id,),
            ).fetchone()
        assert row["repo_root"] is None
        assert row["anomaly_domain"] is None
