"""
Stage 2 — independent fix verification tests.

Covers kernel/anomaly_verifier.py: re-running the affected repo's pytest
suite on base_ref vs. a proposed fix branch inside a disposable worktree,
and the resulting fail->pass / pass->fail / no-suite-found verdicts.

Note: base_ref is always a commit SHA (never a branch name) in these tests.
Branch names like "master" are checked out in the ORIGIN repo's main
working tree, and git refuses to check out the same branch in a linked
worktree ("already used by worktree at ..."). Detached-HEAD-by-SHA has no
such restriction, which is exactly what create_worktree() itself relies on.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from rawos.context.server_scanner import ServerAnomaly
from rawos.kernel.worktree import create_worktree, remove_worktree


def _git(*args: str, cwd: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _git_out(*args: str, cwd: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _make_anomaly(repo_path: str, kind: str = "service_failed") -> ServerAnomaly:
    return ServerAnomaly(
        kind=kind,
        affected_path=repo_path,
        service="toy.service",
        detail="toy anomaly for verifier tests",
        last_log="",
        severity=8,
    )


def _init_python_repo(repo: Path) -> str:
    """Create a minimal git repo with a pytest suite testing toy.add(). Returns the initial commit SHA."""
    repo.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=str(repo))
    _git("config", "user.email", "test@rawos.local", cwd=str(repo))
    _git("config", "user.name", "rawos-test", cwd=str(repo))

    (repo / "toy.py").write_text("def add(a, b):\n    return a + b - 1  # BUG\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_toy.py").write_text(
        "from toy import add\n\n"
        "def test_add():\n"
        "    assert add(2, 2) == 4\n"
    )
    _git("add", ".", cwd=str(repo))
    _git("commit", "-q", "-m", "init (buggy)", cwd=str(repo))

    # Point _discover_python_interpreter at rawos's own venv, which has
    # pytest installed — repo_path/venv/bin/python3 takes priority over
    # bare "python3" (see anomaly_verifier._discover_python_interpreter).
    rawos_venv = Path("/root/rawos/venv")
    if rawos_venv.exists():
        os.symlink(rawos_venv, repo / "venv")

    return _git_out("rev-parse", "HEAD", cwd=str(repo))


@pytest.fixture
async def toy_repo_worktree(tmp_path):
    repo = tmp_path / "toy-repo"
    sha0 = _init_python_repo(repo)
    worktree_path = await create_worktree(str(repo))
    assert worktree_path is not None
    yield repo, worktree_path, sha0
    await remove_worktree(worktree_path)


class TestVerifyFixKindGuard:
    @pytest.mark.asyncio
    async def test_disk_anomaly_raises(self, tmp_path):
        from rawos.kernel.anomaly_verifier import verify_fix

        anomaly = _make_anomaly("/", kind="disk_critical")
        with pytest.raises(ValueError):
            await verify_fix(anomaly, str(tmp_path), "rawos/fix-whatever")


class TestVerifyFixOutcomes:
    @pytest.mark.asyncio
    async def test_fail_to_pass_resolved_true(self, toy_repo_worktree):
        from rawos.kernel.anomaly_verifier import verify_fix

        repo, worktree_path, sha0 = toy_repo_worktree
        worktree = Path(worktree_path)

        _git("checkout", "-q", "-b", "rawos/fix-toy-add", cwd=worktree_path)
        (worktree / "toy.py").write_text("def add(a, b):\n    return a + b\n")
        _git("add", "toy.py", cwd=worktree_path)
        _git("commit", "-q", "-m", "rawos: fix off-by-one in add", cwd=worktree_path)

        anomaly = _make_anomaly(str(repo))
        result = await verify_fix(anomaly, worktree_path, "rawos/fix-toy-add", base_ref=sha0)

        assert result.resolved is True
        assert result.method.startswith("pytest:")
        assert "RESOLVED" in result.evidence

    @pytest.mark.asyncio
    async def test_fail_to_fail_resolved_false(self, toy_repo_worktree):
        from rawos.kernel.anomaly_verifier import verify_fix

        repo, worktree_path, sha0 = toy_repo_worktree
        worktree = Path(worktree_path)

        _git("checkout", "-q", "-b", "rawos/fix-toy-noop", cwd=worktree_path)
        (worktree / "README.md").write_text("unrelated change\n")
        _git("add", "README.md", cwd=worktree_path)
        _git("commit", "-q", "-m", "rawos: unrelated change, bug remains", cwd=worktree_path)

        anomaly = _make_anomaly(str(repo))
        result = await verify_fix(anomaly, worktree_path, "rawos/fix-toy-noop", base_ref=sha0)

        assert result.resolved is False
        assert "NOT RESOLVED" in result.evidence

    @pytest.mark.asyncio
    async def test_pass_to_fail_regression_resolved_false(self, toy_repo_worktree):
        from rawos.kernel.anomaly_verifier import verify_fix

        repo, worktree_path, _sha0 = toy_repo_worktree
        worktree = Path(worktree_path)

        # Second commit on origin's master fixes the bug -> a passing baseline.
        (Path(repo) / "toy.py").write_text("def add(a, b):\n    return a + b\n")
        _git("add", "toy.py", cwd=str(repo))
        _git("commit", "-q", "-m", "fix bug on master", cwd=str(repo))
        sha_fixed = _git_out("rev-parse", "master", cwd=str(repo))

        _git("checkout", "-q", sha_fixed, cwd=worktree_path)
        _git("checkout", "-q", "-b", "rawos/fix-breaks-things", cwd=worktree_path)
        (worktree / "toy.py").write_text("def add(a, b):\n    return a - b  # regression\n")
        _git("add", "toy.py", cwd=worktree_path)
        _git("commit", "-q", "-m", "rawos: bad fix, breaks add", cwd=worktree_path)

        anomaly = _make_anomaly(str(repo))
        result = await verify_fix(anomaly, worktree_path, "rawos/fix-breaks-things", base_ref=sha_fixed)

        assert result.resolved is False
        assert "REGRESSION" in result.evidence
        assert "DO NOT MERGE" in result.evidence

    @pytest.mark.asyncio
    async def test_pass_to_pass_inconclusive(self, toy_repo_worktree):
        from rawos.kernel.anomaly_verifier import verify_fix

        repo, worktree_path, _sha0 = toy_repo_worktree
        worktree = Path(worktree_path)

        (Path(repo) / "toy.py").write_text("def add(a, b):\n    return a + b\n")
        _git("add", "toy.py", cwd=str(repo))
        _git("commit", "-q", "-m", "fix bug on master", cwd=str(repo))
        sha_fixed = _git_out("rev-parse", "master", cwd=str(repo))

        _git("checkout", "-q", sha_fixed, cwd=worktree_path)
        _git("checkout", "-q", "-b", "rawos/fix-cosmetic", cwd=worktree_path)
        (worktree / "README.md").write_text("cosmetic\n")
        _git("add", "README.md", cwd=worktree_path)
        _git("commit", "-q", "-m", "rawos: cosmetic change", cwd=worktree_path)

        anomaly = _make_anomaly(str(repo))
        result = await verify_fix(anomaly, worktree_path, "rawos/fix-cosmetic", base_ref=sha_fixed)

        assert result.resolved is None
        assert "INCONCLUSIVE" in result.evidence

    @pytest.mark.asyncio
    async def test_no_test_suite_returns_none(self, tmp_path):
        from rawos.kernel.anomaly_verifier import verify_fix

        repo = tmp_path / "no-tests-repo"
        repo.mkdir()
        _git("init", "-q", cwd=str(repo))
        _git("config", "user.email", "test@rawos.local", cwd=str(repo))
        _git("config", "user.name", "rawos-test", cwd=str(repo))
        (repo / "README.md").write_text("no tests here\n")
        _git("add", ".", cwd=str(repo))
        _git("commit", "-q", "-m", "init", cwd=str(repo))
        sha0 = _git_out("rev-parse", "HEAD", cwd=str(repo))

        worktree_path = await create_worktree(str(repo))
        assert worktree_path is not None
        try:
            _git("checkout", "-q", "-b", "rawos/fix-something", cwd=worktree_path)

            anomaly = _make_anomaly(str(repo))
            result = await verify_fix(anomaly, worktree_path, "rawos/fix-something", base_ref=sha0)

            assert result.resolved is None
            assert result.method == "none"
            assert "no pytest suite discoverable" in result.evidence
        finally:
            await remove_worktree(worktree_path)


class TestInterpreterDiscovery:
    def test_prefers_repo_venv(self, tmp_path):
        from rawos.kernel.anomaly_verifier import _discover_python_interpreter

        repo = tmp_path / "repo-with-venv"
        (repo / "venv" / "bin").mkdir(parents=True)
        py = repo / "venv" / "bin" / "python3"
        py.write_text("#!/bin/sh\n")
        py.chmod(0o755)

        assert _discover_python_interpreter(repo) == str(py)

    def test_falls_back_to_system_python(self, tmp_path):
        from rawos.kernel.anomaly_verifier import _discover_python_interpreter

        repo = tmp_path / "repo-no-venv"
        repo.mkdir()
        assert _discover_python_interpreter(repo) == "python3"
