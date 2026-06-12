"""
WindowsServiceManager — PowerShell Get-Service / Restart-Service (SCM).

Key design decisions:
- supports_reversible_apply=False permanently. Windows backend is EXPERIMENTAL
  and never live until a Windows host verifies it. The structural gate ensures
  auto-apply cannot reach this backend regardless of autonomy-ladder state.
- list_failed(): Auto-start services currently stopped (StartType=Automatic,
  Status=Stopped). Windows SCM has no "failed" state as such — stopped
  automatic services are the closest equivalent to systemd's "failed" units.
- is_active(): Status == 'Running' via Get-Service.
- restart(): Restart-Service -Force -ErrorAction Stop. Exit code 0 = success.

All calls use powershell.exe argv list (no shell quoting issues).

EXPERIMENTAL: never live until a Windows host verifies it.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from rawos.kernel.arch.windows import WindowsServiceManager


def _mock_run(stdout: str, returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


# ── supports_reversible_apply ────────────────────────────────────────────────

def test_supports_reversible_apply_is_false():
    mgr = WindowsServiceManager()
    assert mgr.supports_reversible_apply is False


# ── list_failed ──────────────────────────────────────────────────────────────

def test_list_failed_returns_stopped_automatic_service_names():
    mgr = WindowsServiceManager()
    output = "Spooler\nwuauserv\n"
    with patch("rawos.kernel.arch.windows.subprocess.run",
               return_value=_mock_run(output)):
        result = mgr.list_failed()
    assert result == ["Spooler", "wuauserv"]


def test_list_failed_returns_empty_on_no_output():
    mgr = WindowsServiceManager()
    with patch("rawos.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("")):
        assert mgr.list_failed() == []


def test_list_failed_returns_empty_on_subprocess_failure():
    mgr = WindowsServiceManager()
    with patch("rawos.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("", returncode=1)):
        assert mgr.list_failed() == []


def test_list_failed_returns_empty_on_exception():
    mgr = WindowsServiceManager()
    with patch("rawos.kernel.arch.windows.subprocess.run",
               side_effect=OSError("powershell unavailable")):
        assert mgr.list_failed() == []


def test_list_failed_uses_get_service_filter_command():
    """The PowerShell command must filter by Automatic+Stopped (not all stopped)."""
    mgr = WindowsServiceManager()
    with patch("rawos.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("")) as mock_run:
        mgr.list_failed()
    args = mock_run.call_args[0][0]
    cmd = " ".join(args)
    assert "Get-Service" in cmd
    assert "Automatic" in cmd
    assert "Stopped" in cmd


# ── is_active ────────────────────────────────────────────────────────────────

def test_is_active_returns_true_when_status_running():
    mgr = WindowsServiceManager()
    with patch("rawos.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("Running\n")):
        assert mgr.is_active("Spooler") is True


def test_is_active_returns_false_when_status_stopped():
    mgr = WindowsServiceManager()
    with patch("rawos.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("Stopped\n")):
        assert mgr.is_active("Spooler") is False


def test_is_active_returns_false_on_empty_output():
    """Empty output means service not found (SilentlyContinue suppresses error)."""
    mgr = WindowsServiceManager()
    with patch("rawos.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("")):
        assert mgr.is_active("NonExistent") is False


def test_is_active_returns_false_on_exception():
    mgr = WindowsServiceManager()
    with patch("rawos.kernel.arch.windows.subprocess.run",
               side_effect=OSError("powershell unavailable")):
        assert mgr.is_active("Spooler") is False


# ── restart ──────────────────────────────────────────────────────────────────

def test_restart_calls_restart_service_with_force():
    mgr = WindowsServiceManager()
    with patch("rawos.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("", returncode=0)) as mock_run:
        result = mgr.restart("Spooler")
    assert result is True
    args = mock_run.call_args[0][0]
    cmd = " ".join(args)
    assert "Restart-Service" in cmd
    assert "Spooler" in cmd
    assert "-Force" in cmd


def test_restart_returns_false_on_nonzero_exit():
    mgr = WindowsServiceManager()
    with patch("rawos.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("", returncode=1)):
        assert mgr.restart("Spooler") is False


def test_restart_returns_false_on_exception():
    mgr = WindowsServiceManager()
    with patch("rawos.kernel.arch.windows.subprocess.run",
               side_effect=OSError("powershell unavailable")):
        assert mgr.restart("Spooler") is False
