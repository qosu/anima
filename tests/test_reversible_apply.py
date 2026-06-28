"""
Stage 3 — kernel.reversible_apply: fast-forward apply + health-gated
auto-rollback (see docs/plans/squishy-watching-stroustrup.md).

These tests cover the git-level apply/rollback mechanics and safety
refusal using real git repos. They never touch systemd directly — the
"restart fails" path is exercised by pointing at a unit name that does not
exist, which is a real `systemctl restart` failure with no side effects.
The health-gate-success path (real systemd) is covered separately in
tests/test_reversible_apply_canary.py.
"""
from __future__ import annotations

import subprocess

import pytest

from anima.kernel.reversible_apply import ReversibleApplyError, reversible_apply


def _git(*args: str, cwd: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _git_out(*args: str, cwd: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


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


async def _always_healthy() -> bool:
    return True


@pytest.mark.asyncio
class TestReversibleApplySafety:
    async def test_refuses_rawos_own_source_tree(self):
        with pytest.raises(ReversibleApplyError):
            await reversible_apply(
                "/root/rawos", "rawos/fix-x", "rawos",
                health_check=_always_healthy,
            )


@pytest.mark.asyncio
class TestReversibleApplyMerge:
    async def test_non_fast_forward_branch_is_not_applied(self, repo):
        # rawos/fix-x branches off the initial commit...
        _git("checkout", "-q", "-b", "rawos/fix-x", cwd=str(repo))
        (repo / "fix.txt").write_text("fix\n")
        _git("add", "fix.txt", cwd=str(repo))
        _git("commit", "-q", "-m", "rawos: fix x", cwd=str(repo))

        # ...but main moves on with an unrelated commit, so fix-x is no
        # longer a fast-forward of main's new HEAD.
        _git("checkout", "-q", "main", cwd=str(repo))
        (repo / "app.txt").write_text("v2\n")
        _git("add", "app.txt", cwd=str(repo))
        _git("commit", "-q", "-m", "v2", cwd=str(repo))
        before_sha = _git_out("rev-parse", "HEAD", cwd=str(repo))

        result = await reversible_apply(
            str(repo), "rawos/fix-x", "rawos-nonexistent-test-unit",
            health_check=_always_healthy,
        )

        assert result.applied is False
        assert result.rolled_back is False
        assert result.before_sha == before_sha
        assert result.after_sha is None
        assert _git_out("rev-parse", "HEAD", cwd=str(repo)) == before_sha


@pytest.mark.asyncio
class TestReversibleApplyRollback:
    async def test_restart_failure_rolls_back_to_before_sha(self, repo):
        before_sha = _git_out("rev-parse", "HEAD", cwd=str(repo))

        _git("checkout", "-q", "-b", "rawos/fix-x", cwd=str(repo))
        (repo / "app.txt").write_text("v2\n")
        _git("add", "app.txt", cwd=str(repo))
        _git("commit", "-q", "-m", "rawos: fix x", cwd=str(repo))
        _git("checkout", "-q", "main", cwd=str(repo))

        result = await reversible_apply(
            str(repo), "rawos/fix-x", "rawos-nonexistent-test-unit",
            health_check=_always_healthy,
            timeout_s=2, poll_interval_s=0.5,
        )

        assert result.applied is True
        assert result.rolled_back is True
        assert result.healthy is False
        assert result.before_sha == before_sha
        assert "restart" in result.detail
        assert _git_out("rev-parse", "HEAD", cwd=str(repo)) == before_sha
        assert (repo / "app.txt").read_text() == "v1\n"
