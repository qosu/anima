"""
Stage 3 — autonomy track record: DB persistence (get/update_track_record)
and git-based merge detection (is_branch_merged).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile

import pytest

import anima.db as db
from anima.kernel.track_record import (
    GRADUATION_THRESHOLD,
    get_track_record,
    is_branch_merged,
    update_track_record,
)
from anima.models import User


def _git(*args: str, cwd: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _git_out(*args: str, cwd: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


class TestTrackRecordDB:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        db.init(os.path.join(self.tmp, "test.db"))
        self.user = db.create_user(User(
            email=f"track-record-{id(self)}@test.com",
            password_hash=hashlib.sha256(b"pass").hexdigest(),
        ))

    def test_get_track_record_returns_default_when_absent(self):
        state = get_track_record(self.user.id, "/root/some-repo", "service_failed:foo.service")
        assert state.verified_successes == 0
        assert state.graduated is False
        assert state.pending_since is None

    def test_update_track_record_persists_and_round_trips(self):
        update_track_record(
            self.user.id, "/root/some-repo", "service_failed:foo.service",
            anomaly_present=False, branch_merged=True,
            fix_branch="anima/fix-a", fix_sha="aaa", now=100,
        )
        state = get_track_record(self.user.id, "/root/some-repo", "service_failed:foo.service")
        assert state.pending_since == 100
        assert state.last_fix_branch == "anima/fix-a"
        assert state.last_outcome == "merged_pending_stability"

        update_track_record(
            self.user.id, "/root/some-repo", "service_failed:foo.service",
            anomaly_present=False, branch_merged=True,
            fix_branch="anima/fix-a", fix_sha="aaa", now=200,
        )
        state = get_track_record(self.user.id, "/root/some-repo", "service_failed:foo.service")
        assert state.verified_successes == 1
        assert state.pending_since is None

    def test_update_track_record_noop_when_not_merged_does_not_create_row(self):
        update_track_record(
            self.user.id, "/root/some-repo", "service_failed:bar.service",
            anomaly_present=True, branch_merged=False,
            fix_branch="anima/fix-z", fix_sha="zzz", now=100,
        )
        state = get_track_record(self.user.id, "/root/some-repo", "service_failed:bar.service")
        assert state.verified_successes == 0
        assert state.last_fix_branch is None

    def test_class_graduates_after_three_verified_successes(self):
        assert GRADUATION_THRESHOLD == 3
        domain = "service_failed:baz.service"
        for cycle, branch in enumerate(["anima/fix-1", "anima/fix-2", "anima/fix-3"]):
            update_track_record(
                self.user.id, "/root/some-repo", domain,
                anomaly_present=False, branch_merged=True,
                fix_branch=branch, fix_sha=branch, now=cycle * 1000,
            )
            update_track_record(
                self.user.id, "/root/some-repo", domain,
                anomaly_present=False, branch_merged=True,
                fix_branch=branch, fix_sha=branch, now=cycle * 1000 + 500,
            )
        state = get_track_record(self.user.id, "/root/some-repo", domain)
        assert state.verified_successes == 3
        assert state.graduated is True


class TestIsBranchMerged:
    @pytest.fixture
    def origin_and_clone(self, tmp_path):
        origin = tmp_path / "origin"
        origin.mkdir()
        _git("init", "-q", "-b", "main", cwd=str(origin))
        _git("config", "user.email", "test@anima.local", cwd=str(origin))
        _git("config", "user.name", "anima-test", cwd=str(origin))
        _git("config", "receive.denyCurrentBranch", "updateInstead", cwd=str(origin))
        (origin / "README.md").write_text("init\n")
        _git("add", ".", cwd=str(origin))
        _git("commit", "-q", "-m", "init", cwd=str(origin))

        clone = tmp_path / "clone"
        _git("clone", "-q", str(origin), str(clone), cwd=str(tmp_path))
        _git("config", "user.email", "test@anima.local", cwd=str(clone))
        _git("config", "user.name", "anima-test", cwd=str(clone))
        return origin, clone

    @pytest.mark.asyncio
    async def test_unmerged_branch_returns_false(self, origin_and_clone):
        _origin, clone = origin_and_clone

        _git("checkout", "-q", "-b", "anima/fix-x", cwd=str(clone))
        (clone / "fix.txt").write_text("fix\n")
        _git("add", "fix.txt", cwd=str(clone))
        _git("commit", "-q", "-m", "anima: fix x", cwd=str(clone))
        sha = _git_out("rev-parse", "HEAD", cwd=str(clone))

        assert await is_branch_merged(str(clone), sha) is False

    @pytest.mark.asyncio
    async def test_merged_branch_returns_true_after_fetch(self, origin_and_clone):
        origin, clone = origin_and_clone

        _git("checkout", "-q", "-b", "anima/fix-x", cwd=str(clone))
        (clone / "fix.txt").write_text("fix\n")
        _git("add", "fix.txt", cwd=str(clone))
        _git("commit", "-q", "-m", "anima: fix x", cwd=str(clone))
        sha = _git_out("rev-parse", "HEAD", cwd=str(clone))

        # Simulate a human merging the fix branch into origin's default branch.
        _git("push", "-q", "origin", "anima/fix-x", cwd=str(clone))
        _git("checkout", "-q", "main", cwd=str(clone))
        _git("merge", "-q", "--no-ff", "-m", "merge fix", "anima/fix-x", cwd=str(clone))
        _git("push", "-q", "origin", "main", cwd=str(clone))
        _git("fetch", "-q", "origin", cwd=str(clone))

        assert await is_branch_merged(str(clone), sha) is True

    @pytest.mark.asyncio
    async def test_no_origin_remote_returns_false(self, tmp_path):
        repo = tmp_path / "no-origin"
        repo.mkdir()
        _git("init", "-q", cwd=str(repo))
        _git("config", "user.email", "test@anima.local", cwd=str(repo))
        _git("config", "user.name", "anima-test", cwd=str(repo))
        (repo / "README.md").write_text("init\n")
        _git("add", ".", cwd=str(repo))
        _git("commit", "-q", "-m", "init", cwd=str(repo))
        sha = _git_out("rev-parse", "HEAD", cwd=str(repo))

        assert await is_branch_merged(str(repo), sha) is False
