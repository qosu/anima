"""
WindowsShellPolicy — PowerShell via cmd.exe passthrough. No ulimit.

Design: wrap() produces a command that cmd.exe (create_subprocess_shell's
default shell on Windows) can execute by invoking powershell.exe -NonInteractive.
The inner PowerShell script uses Set-Location for workdir isolation.

Documented gap: no ulimit equivalent on Windows. Job Objects are the correct
Windows resource-limit mechanism but are not implemented here — deferred and
stated, not hidden.

readonly_whitelist(): empty systemctl_subcmds and journalctl_blocked — Windows
has neither. Get-Service / Get-WinEvent are the Windows equivalents and will
be added to _is_bash_readonly_safe when Stage C goes live (future extension,
not yet implemented).

EXPERIMENTAL: never live until a Windows host verifies it.
"""
from __future__ import annotations

from rawos.kernel.arch.windows import WindowsShellPolicy


def test_wrap_uses_powershell():
    policy = WindowsShellPolicy()
    cmd, _ = policy.wrap("pytest tests/", "C:\\workdir")
    assert "powershell.exe" in cmd


def test_wrap_uses_set_location_for_workdir():
    policy = WindowsShellPolicy()
    cmd, _ = policy.wrap("pytest tests/", "C:\\workdir")
    assert "Set-Location" in cmd
    assert "C:\\workdir" in cmd


def test_wrap_appends_command():
    policy = WindowsShellPolicy()
    cmd, _ = policy.wrap("pytest tests/", "C:\\workdir")
    assert "pytest tests/" in cmd


def test_wrap_excludes_ulimit():
    """No ulimit on Windows — Job Objects are the equivalent (deferred, documented)."""
    policy = WindowsShellPolicy()
    cmd, _ = policy.wrap("pytest", "C:\\workdir")
    assert "ulimit" not in cmd


def test_wrap_returns_empty_kwargs():
    policy = WindowsShellPolicy()
    _, kwargs = policy.wrap("pytest", "C:\\workdir")
    assert kwargs == {}


def test_readonly_whitelist_systemctl_subcmds_empty():
    """No systemctl on Windows."""
    policy = WindowsShellPolicy()
    wl = policy.readonly_whitelist()
    assert wl.systemctl_subcmds == frozenset()


def test_readonly_whitelist_journalctl_blocked_empty():
    """No journalctl on Windows."""
    policy = WindowsShellPolicy()
    wl = policy.readonly_whitelist()
    assert wl.journalctl_blocked == ()
