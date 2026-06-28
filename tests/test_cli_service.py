"""tests/test_cli_service.py — TDD for `rawos service` CLI group (Milestone 5 Step 3)."""
from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from anima.cli.main import cli


def _runner():
    return CliRunner()


# ── service install ───────────────────────────────────────────────────────────


def test_service_install_calls_generate_and_install_unit():
    runner = _runner()
    generated_content = "[Unit]\nDescription=rawos service\n"
    mock_mgr = MagicMock()
    mock_mgr.generate_unit.return_value = generated_content

    with tempfile.TemporaryDirectory() as unit_dir:
        with patch("anima.cli.main.LinuxServiceManager", return_value=mock_mgr):
            result = runner.invoke(cli, [
                "service", "install",
                "--name", "rawos",
                "--exec-start", "/venv/bin/uvicorn rawos.api.app:app",
                "--working-dir", "/srv/rawos",
                "--env-file", "/srv/rawos/.env",
                "--unit-dir", unit_dir,
            ])

    assert result.exit_code == 0, result.output
    mock_mgr.generate_unit.assert_called_once()
    mock_mgr.install_unit.assert_called_once_with(
        "rawos", generated_content, unit_dir=unit_dir
    )


def test_service_install_prints_success_message():
    runner = _runner()
    mock_mgr = MagicMock()
    mock_mgr.generate_unit.return_value = "[Unit]\n"

    with tempfile.TemporaryDirectory() as unit_dir:
        with patch("anima.cli.main.LinuxServiceManager", return_value=mock_mgr):
            result = runner.invoke(cli, [
                "service", "install",
                "--exec-start", "/bin/true",
                "--working-dir", "/srv",
                "--env-file", "/srv/.env",
                "--unit-dir", unit_dir,
            ])

    assert "installed" in result.output.lower() or "rawos" in result.output


def test_service_install_uses_default_name_rawos():
    runner = _runner()
    mock_mgr = MagicMock()
    mock_mgr.generate_unit.return_value = "[Unit]\n"

    with tempfile.TemporaryDirectory() as unit_dir:
        with patch("anima.cli.main.LinuxServiceManager", return_value=mock_mgr):
            result = runner.invoke(cli, [
                "service", "install",
                "--exec-start", "/bin/true",
                "--working-dir", "/srv",
                "--env-file", "/srv/.env",
                "--unit-dir", unit_dir,
            ])

    call_kwargs = mock_mgr.generate_unit.call_args
    assert call_kwargs[1].get("name", call_kwargs[0][0] if call_kwargs[0] else None) == "rawos" or \
           "rawos" in str(call_kwargs)


# ── service uninstall ─────────────────────────────────────────────────────────


def test_service_uninstall_calls_uninstall_unit():
    runner = _runner()
    mock_mgr = MagicMock()

    with tempfile.TemporaryDirectory() as unit_dir:
        with patch("anima.cli.main.LinuxServiceManager", return_value=mock_mgr):
            result = runner.invoke(cli, [
                "service", "uninstall",
                "--name", "rawos",
                "--unit-dir", unit_dir,
            ])

    assert result.exit_code == 0, result.output
    mock_mgr.uninstall_unit.assert_called_once_with("rawos", unit_dir=unit_dir)


# ── service status ────────────────────────────────────────────────────────────


def test_service_status_shows_active_when_running():
    runner = _runner()
    mock_mgr = MagicMock()
    mock_mgr.is_active.return_value = True

    with patch("anima.cli.main.LinuxServiceManager", return_value=mock_mgr):
        result = runner.invoke(cli, ["service", "status", "--name", "rawos"])

    assert result.exit_code == 0
    assert "active" in result.output.lower()
    mock_mgr.is_active.assert_called_once_with("rawos")


def test_service_status_shows_inactive_when_stopped():
    runner = _runner()
    mock_mgr = MagicMock()
    mock_mgr.is_active.return_value = False

    with patch("anima.cli.main.LinuxServiceManager", return_value=mock_mgr):
        result = runner.invoke(cli, ["service", "status", "--name", "rawos"])

    assert "inactive" in result.output.lower() or "not" in result.output.lower()


# ── service restart ───────────────────────────────────────────────────────────


def test_service_restart_calls_restart_and_reports_success():
    runner = _runner()
    mock_mgr = MagicMock()
    mock_mgr.restart.return_value = True

    with patch("anima.cli.main.LinuxServiceManager", return_value=mock_mgr):
        result = runner.invoke(cli, ["service", "restart", "--name", "rawos"])

    assert result.exit_code == 0
    mock_mgr.restart.assert_called_once_with("rawos")
    assert "restart" in result.output.lower() or "ok" in result.output.lower()


def test_service_restart_exits_nonzero_on_failure():
    runner = _runner()
    mock_mgr = MagicMock()
    mock_mgr.restart.return_value = False

    with patch("anima.cli.main.LinuxServiceManager", return_value=mock_mgr):
        result = runner.invoke(cli, ["service", "restart", "--name", "rawos"])

    assert result.exit_code != 0


# ── service logs ──────────────────────────────────────────────────────────────


def test_service_logs_calls_tail_and_prints():
    runner = _runner()
    mock_log = MagicMock()
    mock_log.tail.return_value = "line1\nline2\n"

    with patch("anima.cli.main.LinuxLogReader", return_value=mock_log):
        result = runner.invoke(cli, ["service", "logs", "--name", "rawos", "-n", "10"])

    assert result.exit_code == 0
    assert "line1" in result.output
    mock_log.tail.assert_called_once_with("rawos", 10)


def test_service_logs_default_lines_50():
    runner = _runner()
    mock_log = MagicMock()
    mock_log.tail.return_value = ""

    with patch("anima.cli.main.LinuxLogReader", return_value=mock_log):
        runner.invoke(cli, ["service", "logs"])

    mock_log.tail.assert_called_once_with("rawos", 50)
