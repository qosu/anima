"""rawos/cli/frontdoor_entry.py — lockout-proof SSH ForceCommand entrypoint.

This module is the ONLY thing `rawos frontdoor install` points ForceCommand at.
It must stay syntactically trivial and defer importing `rawos.cli.main` to
call-time: if that module ever fails to import (syntax error, broken import
chain), the except branch below is the owner's only way back into a shell.
Keep this file minimal and rarely touched.
"""
from __future__ import annotations

import os


def _run_cli() -> int:
    from rawos.cli.main import main as _cli_main

    return _cli_main() or 0


def _fallback_to_bash() -> None:
    cmd = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    if cmd:
        os.execv("/bin/bash", ["/bin/bash", "-c", cmd])
    else:
        os.execv("/bin/bash", ["-bash"])


def main() -> int:
    try:
        return _run_cli()
    except Exception:
        _fallback_to_bash()
        return 1
