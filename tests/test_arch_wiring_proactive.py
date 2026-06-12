"""
scheduler/proactive._live_health_check — wired to kernel/arch ServiceManager ABI.

Characterization: the _check() closure built by _live_health_check must call
get_arch().service_manager.is_active(service_name) via run_in_executor,
NOT run_bash("systemctl is-active ..."). Stage A: zero behavior change on
Linux — LinuxServiceManager.is_active() implements the identical semantics.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from rawos.scheduler.proactive import _live_health_check


def _mock_arch(is_active_return: bool) -> MagicMock:
    backend = MagicMock()
    backend.service_manager.is_active.return_value = is_active_return
    return backend


def test_live_health_check_calls_service_manager_is_active_not_run_bash(tmp_path):
    """_live_health_check must call service_manager.is_active(), not run_bash."""
    backend = _mock_arch(is_active_return=True)
    repo_root = str(tmp_path)

    check = _live_health_check(repo_root, "some_domain", "rawos.service")

    with patch("rawos.scheduler.proactive.get_arch", return_value=backend), \
         patch("rawos.scheduler.proactive.run_bash",
               new=AsyncMock(side_effect=AssertionError(
                   "run_bash must NOT be called for systemctl is-active"
               ))):
        result = asyncio.run(check())

    assert result is True
    backend.service_manager.is_active.assert_called_once_with("rawos.service")


def test_live_health_check_returns_false_when_service_inactive(tmp_path):
    backend = _mock_arch(is_active_return=False)
    repo_root = str(tmp_path)

    check = _live_health_check(repo_root, "some_domain", "rawos.service")

    with patch("rawos.scheduler.proactive.get_arch", return_value=backend), \
         patch("rawos.scheduler.proactive.run_bash", new=AsyncMock(
               side_effect=AssertionError("run_bash must NOT be called"))):
        result = asyncio.run(check())

    assert result is False
