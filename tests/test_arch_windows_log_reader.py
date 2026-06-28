"""
WindowsLogReader — PowerShell Get-WinEvent (Windows Event Log).

Key design decisions:
- tail(): Get-WinEvent -MaxEvents N limits at source; -ProviderName filter applied
  via Where-Object. Returns Message property, one per line.
- recent_errors(): Level=2 (Error) in Windows Event Log. Relative since-strings
  ("N minutes ago", "N hours ago") are converted to PowerShell AddMinutes/AddHours
  datetime expressions. ISO timestamps are passed as quoted strings.

EXPERIMENTAL: never live until a Windows host verifies it.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from anima.kernel.arch.windows import WindowsLogReader


def _mock_run(stdout: str, returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


# ── tail ─────────────────────────────────────────────────────────────────────

def test_tail_returns_output_stripped():
    reader = WindowsLogReader()
    with patch("anima.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("  event line 1\nevent line 2  \n")):
        result = reader.tail("MyApp", 10)
    assert result == "event line 1\nevent line 2"


def test_tail_returns_empty_on_nonzero_exit():
    reader = WindowsLogReader()
    with patch("anima.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("", returncode=1)):
        assert reader.tail("MyApp", 10) == ""


def test_tail_returns_empty_on_exception():
    reader = WindowsLogReader()
    with patch("anima.kernel.arch.windows.subprocess.run",
               side_effect=OSError("powershell unavailable")):
        assert reader.tail("MyApp", 10) == ""


def test_tail_command_includes_maxevents_and_provider():
    reader = WindowsLogReader()
    with patch("anima.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("")) as mock_run:
        reader.tail("MyApp", 20)
    args = mock_run.call_args[0][0]
    cmd = " ".join(args)
    assert "Get-WinEvent" in cmd
    assert "20" in cmd
    assert "MyApp" in cmd


# ── recent_errors ─────────────────────────────────────────────────────────────

def test_recent_errors_uses_addminutes_for_minutes():
    """'15 minutes ago' → AddMinutes(-15) in PowerShell datetime expression."""
    reader = WindowsLogReader()
    with patch("anima.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("")) as mock_run:
        reader.recent_errors("MyApp", "15 minutes ago")
    args = mock_run.call_args[0][0]
    cmd = " ".join(args)
    assert "AddMinutes(-15)" in cmd
    assert "AddHours" not in cmd


def test_recent_errors_uses_addhours_for_hours():
    reader = WindowsLogReader()
    with patch("anima.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("")) as mock_run:
        reader.recent_errors("MyApp", "2 hours ago")
    args = mock_run.call_args[0][0]
    cmd = " ".join(args)
    assert "AddHours(-2)" in cmd
    assert "AddMinutes" not in cmd


def test_recent_errors_passes_iso_timestamp_as_quoted_string():
    reader = WindowsLogReader()
    with patch("anima.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("")) as mock_run:
        reader.recent_errors("MyApp", "2026-01-15 10:30:00")
    args = mock_run.call_args[0][0]
    cmd = " ".join(args)
    assert "2026-01-15 10:30:00" in cmd
    assert "AddMinutes" not in cmd
    assert "AddHours" not in cmd


def test_recent_errors_filters_level_2_errors():
    """Level=2 is Windows Event Log Error level."""
    reader = WindowsLogReader()
    with patch("anima.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("")) as mock_run:
        reader.recent_errors("MyApp", "15 minutes ago")
    args = mock_run.call_args[0][0]
    cmd = " ".join(args)
    assert "Level=2" in cmd


def test_recent_errors_returns_output_stripped():
    reader = WindowsLogReader()
    with patch("anima.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("  error message  \n")):
        result = reader.recent_errors("MyApp", "15 minutes ago")
    assert result == "error message"


def test_recent_errors_returns_empty_on_exception():
    reader = WindowsLogReader()
    with patch("anima.kernel.arch.windows.subprocess.run",
               side_effect=OSError("powershell unavailable")):
        assert reader.recent_errors("MyApp", "15 minutes ago") == ""


def test_recent_errors_returns_empty_on_nonzero_exit():
    reader = WindowsLogReader()
    with patch("anima.kernel.arch.windows.subprocess.run",
               return_value=_mock_run("", returncode=1)):
        assert reader.recent_errors("MyApp", "15 minutes ago") == ""
