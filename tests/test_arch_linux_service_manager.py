"""
kernel/arch/linux — LinuxServiceManager.

Characterization test: list_failed() must reproduce, byte-for-byte, the
`systemctl list-units --type=service --state=failed --no-legend
--no-pager --plain` command and the not-found-skip filter currently
inlined in context/server_scanner.py:_check_failed_services. Stage A is
a zero-behavior-change extraction — this test is the proof.

is_active()/restart()/supports_reversible_apply are new ABI surface
(not yet wired) but built and tested now per base.py's ServiceManager
Protocol.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from rawos.kernel.arch.linux import LinuxServiceManager


def _mock_run(stdout: str, returncode: int = 0) -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    return result


def test_list_failed_runs_systemctl_list_units_failed():
    mgr = LinuxServiceManager()
    with patch("rawos.kernel.arch.linux.subprocess.run",
               return_value=_mock_run("foo.service loaded failed failed Foo\n")) as mock_run:
        result = mgr.list_failed()

    mock_run.assert_called_once_with(
        ["systemctl", "list-units", "--type=service", "--state=failed",
         "--no-legend", "--no-pager", "--plain"],
        capture_output=True, text=True, timeout=5.0,
    )
    assert result == ["foo.service"]


def test_list_failed_skips_not_found_units():
    mgr = LinuxServiceManager()
    with patch("rawos.kernel.arch.linux.subprocess.run",
               return_value=_mock_run("stale.service not-found failed failed Stale\n")):
        assert mgr.list_failed() == []


def test_list_failed_returns_empty_on_nonzero_exit():
    mgr = LinuxServiceManager()
    with patch("rawos.kernel.arch.linux.subprocess.run",
               return_value=_mock_run("", returncode=1)):
        assert mgr.list_failed() == []


def test_list_failed_returns_empty_on_blank_output():
    mgr = LinuxServiceManager()
    with patch("rawos.kernel.arch.linux.subprocess.run",
               return_value=_mock_run("   \n")):
        assert mgr.list_failed() == []


def test_list_failed_returns_empty_on_exception():
    mgr = LinuxServiceManager()
    with patch("rawos.kernel.arch.linux.subprocess.run",
               side_effect=OSError("boom")):
        assert mgr.list_failed() == []


def test_is_active_true_when_systemctl_reports_active():
    mgr = LinuxServiceManager()
    with patch("rawos.kernel.arch.linux.subprocess.run",
               return_value=_mock_run("active\n")) as mock_run:
        assert mgr.is_active("rawos.service") is True

    mock_run.assert_called_once_with(
        ["systemctl", "is-active", "rawos.service"],
        capture_output=True, text=True, timeout=3.0,
    )


def test_is_active_false_when_systemctl_reports_inactive():
    mgr = LinuxServiceManager()
    with patch("rawos.kernel.arch.linux.subprocess.run",
               return_value=_mock_run("inactive\n")):
        assert mgr.is_active("rawos.service") is False


def test_is_active_false_on_exception():
    mgr = LinuxServiceManager()
    with patch("rawos.kernel.arch.linux.subprocess.run",
               side_effect=OSError("boom")):
        assert mgr.is_active("rawos.service") is False


def test_restart_runs_systemctl_restart():
    mgr = LinuxServiceManager()
    with patch("rawos.kernel.arch.linux.subprocess.run",
               return_value=_mock_run("")) as mock_run:
        mgr.restart("rawos.service")

    mock_run.assert_called_once_with(
        ["systemctl", "restart", "rawos.service"],
        capture_output=True, text=True, timeout=30.0,
    )


def test_restart_returns_true_on_success():
    mgr = LinuxServiceManager()
    with patch("rawos.kernel.arch.linux.subprocess.run",
               return_value=_mock_run("", returncode=0)):
        assert mgr.restart("rawos.service") is True


def test_restart_returns_false_on_failure():
    mgr = LinuxServiceManager()
    with patch("rawos.kernel.arch.linux.subprocess.run",
               return_value=_mock_run("", returncode=1)):
        assert mgr.restart("rawos.service") is False


def test_restart_returns_false_on_exception():
    mgr = LinuxServiceManager()
    with patch("rawos.kernel.arch.linux.subprocess.run",
               side_effect=OSError("systemd unavailable")):
        assert mgr.restart("rawos.service") is False


def test_supports_reversible_apply_is_true_on_linux():
    assert LinuxServiceManager().supports_reversible_apply is True
# Tests to append to test_arch_linux_service_manager.py
# ── Step 2: generate_unit / install_unit / uninstall_unit ────────────────────


import os
import tempfile
import configparser


def test_generate_unit_produces_valid_ini_with_all_sections():
    mgr = LinuxServiceManager()
    content = mgr.generate_unit(
        name="rawos",
        exec_start="/srv/rawos/venv/bin/uvicorn rawos.api.app:app --host 127.0.0.1 --port 8002",
        working_dir="/srv/rawos",
        env_file="/srv/rawos/.env",
        description="rawos AI OS API",
    )
    parser = configparser.ConfigParser()
    parser.read_string(content)
    assert parser.has_section("Unit")
    assert parser.has_section("Service")
    assert parser.has_section("Install")


def test_generate_unit_embeds_exec_start():
    mgr = LinuxServiceManager()
    exec_start = "/venv/bin/uvicorn rawos.api.app:app"
    content = mgr.generate_unit("rawos", exec_start, "/srv", "/srv/.env")
    assert exec_start in content


def test_generate_unit_embeds_working_dir():
    mgr = LinuxServiceManager()
    content = mgr.generate_unit("rawos", "/bin/true", "/custom/workdir", "/custom/.env")
    assert "/custom/workdir" in content


def test_generate_unit_embeds_env_file():
    mgr = LinuxServiceManager()
    content = mgr.generate_unit("rawos", "/bin/true", "/srv", "/custom/path/.env")
    assert "/custom/path/.env" in content


def test_generate_unit_sets_restart_always():
    mgr = LinuxServiceManager()
    content = mgr.generate_unit("rawos", "/bin/true", "/srv", "/srv/.env")
    assert "Restart=always" in content


def test_generate_unit_sets_wanted_by_multi_user_target():
    mgr = LinuxServiceManager()
    content = mgr.generate_unit("rawos", "/bin/true", "/srv", "/srv/.env")
    assert "WantedBy=multi-user.target" in content


def test_generate_unit_default_description_contains_name():
    mgr = LinuxServiceManager()
    content = mgr.generate_unit("myapp", "/bin/true", "/srv", "/srv/.env")
    assert "myapp" in content


def test_install_unit_writes_file_to_unit_dir():
    mgr = LinuxServiceManager()
    with tempfile.TemporaryDirectory() as unit_dir:
        with patch("rawos.kernel.arch.linux.subprocess.run",
                   return_value=_mock_run("")) as mock_run:
            mgr.install_unit("rawos", "[Unit]\nDescription=test\n", unit_dir=unit_dir)

        expected_path = os.path.join(unit_dir, "rawos.service")
        assert os.path.isfile(expected_path)
        assert "[Unit]" in open(expected_path).read()


def test_install_unit_calls_daemon_reload_then_enable():
    mgr = LinuxServiceManager()
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _mock_run("")

    with tempfile.TemporaryDirectory() as unit_dir:
        with patch("rawos.kernel.arch.linux.subprocess.run", side_effect=fake_run):
            mgr.install_unit("rawos", "[Unit]\n", unit_dir=unit_dir)

    assert any("daemon-reload" in " ".join(c) for c in calls)
    assert any("enable" in " ".join(c) for c in calls)
    reload_idx = next(i for i, c in enumerate(calls) if "daemon-reload" in " ".join(c))
    enable_idx = next(i for i, c in enumerate(calls) if "enable" in " ".join(c))
    assert reload_idx < enable_idx, "daemon-reload must run before enable"


def test_uninstall_unit_calls_disable_stop_remove_reload():
    mgr = LinuxServiceManager()
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _mock_run("")

    with tempfile.TemporaryDirectory() as unit_dir:
        unit_path = os.path.join(unit_dir, "rawos.service")
        open(unit_path, "w").write("[Unit]\n")
        with patch("rawos.kernel.arch.linux.subprocess.run", side_effect=fake_run):
            mgr.uninstall_unit("rawos", unit_dir=unit_dir)

    assert any("disable" in " ".join(c) for c in calls)
    assert any("stop" in " ".join(c) for c in calls)
    assert not os.path.exists(unit_path)
    assert any("daemon-reload" in " ".join(c) for c in calls)


def test_uninstall_unit_tolerates_missing_service_file():
    mgr = LinuxServiceManager()
    with tempfile.TemporaryDirectory() as unit_dir:
        with patch("rawos.kernel.arch.linux.subprocess.run",
                   return_value=_mock_run("")):
            mgr.uninstall_unit("nonexistent", unit_dir=unit_dir)  # must not raise


def test_uninstall_unit_tolerates_systemctl_disable_failure():
    mgr = LinuxServiceManager()
    def fake_run(cmd, **kwargs):
        if "disable" in cmd:
            return _mock_run("", returncode=1)
        return _mock_run("")

    with tempfile.TemporaryDirectory() as unit_dir:
        with patch("rawos.kernel.arch.linux.subprocess.run", side_effect=fake_run):
            mgr.uninstall_unit("rawos", unit_dir=unit_dir)  # must not raise
