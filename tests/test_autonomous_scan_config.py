"""Autonomous scan interval must be configurable via settings (env-overridable),
not a hardcoded module constant — see proactive.py autonomous_server_scan_loop."""
import asyncio

from rawos.config import settings
from rawos.scheduler import proactive


def test_autonomous_scan_interval_default_is_600():
    assert settings.autonomous_scan_interval_s == 600


def test_autonomous_scan_loop_sleeps_for_configured_interval(monkeypatch):
    monkeypatch.setattr(settings, "autonomous_scan_interval_s", 1)
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise asyncio.CancelledError()

    async def fake_run_autonomous_scan():
        return None

    monkeypatch.setattr(proactive, "_run_autonomous_scan", fake_run_autonomous_scan)
    monkeypatch.setattr(proactive.asyncio, "sleep", fake_sleep)

    try:
        asyncio.run(proactive.autonomous_server_scan_loop())
    except asyncio.CancelledError:
        pass

    assert sleep_calls == [1]
