"""
Stage 3 — kernel.reversible_apply: full health-gate verification against a
real, throwaway systemd unit (per docs/plans/squishy-watching-stroustrup.md
Stage 3 verification spec: "integration test of canary -> health-gate ->
auto-rollback on a throwaway service; assert a deliberately-bad fix
auto-reverts and the live service ends healthy on the prior version").

Each test creates its own uniquely-named oneshot unit
(/etc/systemd/system/rawos-canary-test-<id>.service) whose ExecStart runs a
health.sh script committed in the test repo, and removes the unit file +
daemon-reloads in a finally block — no existing unit is touched.
"""
from __future__ import annotations

import subprocess
import uuid

import pytest

from rawos.kernel.reversible_apply import reversible_apply
from rawos.kernel.sandbox import run_bash


def _git(*args: str, cwd: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _git_out(*args: str, cwd: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def canary(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=str(repo))
    _git("config", "user.email", "test@rawos.local", cwd=str(repo))
    _git("config", "user.name", "rawos-test", cwd=str(repo))

    service = f"rawos-canary-test-{uuid.uuid4().hex[:8]}.service"
    unit_path = f"/etc/systemd/system/{service}"
    unit = (
        "[Unit]\n"
        "Description=rawos reversible_apply canary test (throwaway)\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart=/bin/bash {repo}/health.sh\n"
    )
    with open(unit_path, "w") as f:
        f.write(unit)
    subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)

    try:
        yield repo, service
    finally:
        subprocess.run(["systemctl", "stop", service], capture_output=True)
        subprocess.run(["rm", "-f", unit_path], capture_output=True)
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True)


def _write_health(repo, exit_code: int, message: str) -> None:
    (repo / "health.sh").write_text(f"#!/bin/bash\necho '{message}'\nexit {exit_code}\n")


async def _is_healthy(repo_root: str, service: str) -> bool:
    result = await run_bash(f"systemctl is-failed {service}", repo_root)
    return result.stdout.strip() != "failed"


@pytest.mark.asyncio
class TestReversibleApplyCanary:
    async def test_good_fix_applies_and_passes_health_gate(self, canary):
        repo, service = canary

        _write_health(repo, 1, "broken")
        _git("add", ".", cwd=str(repo))
        _git("commit", "-q", "-m", "init: broken", cwd=str(repo))

        _git("checkout", "-q", "-b", "rawos/fix-good", cwd=str(repo))
        _write_health(repo, 0, "fixed")
        _git("add", ".", cwd=str(repo))
        _git("commit", "-q", "-m", "rawos: fix it", cwd=str(repo))
        _git("checkout", "-q", "main", cwd=str(repo))
        fix_sha = _git_out("rev-parse", "rawos/fix-good", cwd=str(repo))

        async def health_check() -> bool:
            return await _is_healthy(str(repo), service)

        result = await reversible_apply(
            str(repo), "rawos/fix-good", service,
            health_check=health_check,
            timeout_s=5, poll_interval_s=0.5,
        )

        assert result.applied is True
        assert result.healthy is True
        assert result.rolled_back is False
        assert result.after_sha == fix_sha
        assert _git_out("rev-parse", "HEAD", cwd=str(repo)) == fix_sha

    async def test_bad_fix_auto_reverts_and_service_ends_healthy_on_prior_version(self, canary):
        repo, service = canary

        _write_health(repo, 0, "healthy")
        _git("add", ".", cwd=str(repo))
        _git("commit", "-q", "-m", "init: healthy", cwd=str(repo))
        before_sha = _git_out("rev-parse", "HEAD", cwd=str(repo))

        _git("checkout", "-q", "-b", "rawos/fix-bad", cwd=str(repo))
        _write_health(repo, 1, "this fix is bad")
        _git("add", ".", cwd=str(repo))
        _git("commit", "-q", "-m", "rawos: deliberately bad fix", cwd=str(repo))
        _git("checkout", "-q", "main", cwd=str(repo))

        async def health_check() -> bool:
            return await _is_healthy(str(repo), service)

        result = await reversible_apply(
            str(repo), "rawos/fix-bad", service,
            health_check=health_check,
            timeout_s=2, poll_interval_s=0.5,
        )

        assert result.applied is True
        assert result.healthy is False
        assert result.rolled_back is True
        assert result.before_sha == before_sha
        assert _git_out("rev-parse", "HEAD", cwd=str(repo)) == before_sha
        assert (repo / "health.sh").read_text().strip().endswith("exit 0")

        # The live service ends healthy on the prior (rolled-back) version —
        # _rollback's `systemctl restart` already re-ran health.sh exit 0.
        assert await _is_healthy(str(repo), service) is True
