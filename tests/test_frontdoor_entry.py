"""tests/test_frontdoor_entry.py — TDD for the lockout-proof SSH entrypoint
(rawos.cli.frontdoor_entry) and the `rawos frontdoor install` binary resolution
that points ForceCommand at it."""
from __future__ import annotations

from unittest.mock import patch

import click
import pytest


class TestFrontdoorEntryMain:
    def test_returns_cli_exit_code_on_success(self):
        from rawos.cli.frontdoor_entry import main

        with patch("rawos.cli.frontdoor_entry._run_cli", return_value=0) as mock_run:
            with patch("rawos.cli.frontdoor_entry._fallback_to_bash") as mock_fallback:
                assert main() == 0

        mock_run.assert_called_once()
        mock_fallback.assert_not_called()

    def test_propagates_systemexit_from_cli_without_fallback(self):
        from rawos.cli.frontdoor_entry import main

        with patch("rawos.cli.frontdoor_entry._run_cli", side_effect=SystemExit(3)):
            with patch("rawos.cli.frontdoor_entry._fallback_to_bash") as mock_fallback:
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 3
        mock_fallback.assert_not_called()

    def test_falls_back_to_bash_on_import_or_runtime_error(self):
        from rawos.cli.frontdoor_entry import main

        with patch("rawos.cli.frontdoor_entry._run_cli", side_effect=ImportError("broken cli")):
            with patch("rawos.cli.frontdoor_entry._fallback_to_bash") as mock_fallback:
                assert main() == 1

        mock_fallback.assert_called_once()


class TestFrontdoorEntryFallback:
    def test_passthrough_ssh_original_command(self, monkeypatch):
        from rawos.cli.frontdoor_entry import _fallback_to_bash

        monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "ls -la /tmp")
        with patch("rawos.cli.frontdoor_entry.os.execv") as mock_execv:
            _fallback_to_bash()

        mock_execv.assert_called_once_with("/bin/bash", ["/bin/bash", "-c", "ls -la /tmp"])

    def test_interactive_bash_when_no_ssh_original_command(self, monkeypatch):
        from rawos.cli.frontdoor_entry import _fallback_to_bash

        monkeypatch.delenv("SSH_ORIGINAL_COMMAND", raising=False)
        with patch("rawos.cli.frontdoor_entry.os.execv") as mock_execv:
            _fallback_to_bash()

        mock_execv.assert_called_once_with("/bin/bash", ["-bash"])


class TestResolveFrontdoorBinary:
    def test_returns_path_when_found(self):
        from rawos.cli.main import _resolve_frontdoor_binary

        with patch("shutil.which", return_value="/usr/local/bin/rawos-frontdoor"):
            assert _resolve_frontdoor_binary() == "/usr/local/bin/rawos-frontdoor"

    def test_raises_clickexception_when_missing(self):
        from rawos.cli.main import _resolve_frontdoor_binary

        with patch("shutil.which", return_value=None):
            with pytest.raises(click.ClickException, match="rawos-frontdoor"):
                _resolve_frontdoor_binary()


class TestFrontdoorInstallEntryCmd:
    def test_entry_cmd_uses_rawos_frontdoor_binary(self):
        from click.testing import CliRunner

        from rawos.cli.main import cli

        runner = CliRunner()
        with (
            patch(
                "rawos.cli.main._resolve_frontdoor_binary",
                return_value="/usr/local/bin/rawos-frontdoor",
            ),
            patch("rawos.kernel.arch.linux.LinuxFrontDoor"),
            patch("rawos.kernel.frontdoor.install_with_deadman") as mock_install,
        ):
            result = runner.invoke(cli, ["frontdoor", "install"])

        assert result.exit_code == 0, result.output
        args, kwargs = mock_install.call_args
        entry_cmd = args[1] if len(args) > 1 else kwargs.get("entry_command")
        assert entry_cmd == "/usr/local/bin/rawos-frontdoor frontdoor enter"

    def test_install_fails_clearly_if_rawos_frontdoor_binary_missing(self):
        from click.testing import CliRunner

        from rawos.cli.main import cli

        runner = CliRunner()
        with patch("shutil.which", return_value=None):
            result = runner.invoke(cli, ["frontdoor", "install"])

        assert result.exit_code != 0
        assert "rawos-frontdoor" in result.output
