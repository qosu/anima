"""
WindowsResourceProbe — uses shutil.disk_usage (same as macOS).

Windows has no df --output=pcent; shutil.disk_usage (statvfs equivalent via
GetDiskFreeSpaceEx) is the correct Windows approach.

EXPERIMENTAL: this backend is never live until a Windows host verifies it.
"""
from __future__ import annotations

from collections import namedtuple
from unittest.mock import patch

from rawos.kernel.arch.windows import WindowsResourceProbe

DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])


def test_disk_percent_returns_used_percent():
    probe = WindowsResourceProbe()
    with patch("rawos.kernel.arch.windows.shutil.disk_usage",
               return_value=DiskUsage(total=200, used=150, free=50)):
        assert probe.disk_percent("C:\\") == 75


def test_disk_percent_rounds_down():
    probe = WindowsResourceProbe()
    with patch("rawos.kernel.arch.windows.shutil.disk_usage",
               return_value=DiskUsage(total=100, used=33, free=67)):
        assert probe.disk_percent("C:\\") == 33


def test_disk_percent_returns_none_on_exception():
    probe = WindowsResourceProbe()
    with patch("rawos.kernel.arch.windows.shutil.disk_usage",
               side_effect=OSError("no such drive")):
        assert probe.disk_percent("Z:\\") is None


def test_disk_percent_returns_none_on_zero_total():
    probe = WindowsResourceProbe()
    with patch("rawos.kernel.arch.windows.shutil.disk_usage",
               return_value=DiskUsage(total=0, used=0, free=0)):
        assert probe.disk_percent("C:\\") is None
