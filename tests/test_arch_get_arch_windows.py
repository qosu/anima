"""
get_arch() with arch_override="windows" returns a Backend with Windows implementations.

Tests run on any host (Linux/macOS) via arch_override. The lru_cache key is
the OS enum value so LINUX, MACOS, and WINDOWS backends are cached independently.

EXPERIMENTAL: this backend is never live until a Windows host verifies it.
"""
from __future__ import annotations

from rawos.config import Settings
from rawos.kernel.arch import _build_backend, get_arch
from rawos.kernel.arch.windows import (
    WindowsLogReader,
    WindowsResourceProbe,
    WindowsServiceManager,
    WindowsShellPolicy,
)


def test_get_arch_windows_returns_windows_backend_classes():
    _build_backend.cache_clear()
    try:
        backend = get_arch(Settings(arch_override="windows"))
        assert isinstance(backend.resource_probe, WindowsResourceProbe)
        assert isinstance(backend.service_manager, WindowsServiceManager)
        assert isinstance(backend.log_reader, WindowsLogReader)
        assert isinstance(backend.shell_policy, WindowsShellPolicy)
    finally:
        _build_backend.cache_clear()


def test_get_arch_windows_service_manager_supports_reversible_apply_is_false():
    _build_backend.cache_clear()
    try:
        backend = get_arch(Settings(arch_override="windows"))
        assert backend.service_manager.supports_reversible_apply is False
    finally:
        _build_backend.cache_clear()
