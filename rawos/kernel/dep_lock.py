"""rawos/kernel/dep_lock.py — SHP.7 I-SEC9: dependency lock drift detection.

Compares the currently installed pip packages against requirements.lock,
generated from `pip freeze` at a known-good state. Any addition, removal,
or version change is reported as drift and emitted to the audit chain at boot.

This is a detective control — it cannot prevent a supply-chain compromise that
has already happened, but it ensures the compromise is visible at next boot and
recorded in the tamper-evident chain before any subsequent action is taken.

Limitation: pip freeze comparison catches version drift, not hash-level
tampering of wheel contents. Full preventive pip hash-checking (--require-hashes)
requires a hashes-annotated lockfile and is deferred to a follow-up hardening
pass (residual risk documented in SHP plan).
"""
from __future__ import annotations

import dataclasses
import subprocess
import sys
from pathlib import Path
from typing import Sequence

_DEFAULT_LOCK_PATH = Path("/root/rawos/requirements.lock")


@dataclasses.dataclass(frozen=True)
class DepDriftResult:
    ok: bool
    added: Sequence[str]
    removed: Sequence[str]
    changed: Sequence[str]

    @property
    def summary(self) -> str:
        if self.ok:
            return "dep lock OK"
        parts = []
        if self.added:
            parts.append(f"added({len(self.added)})")
        if self.removed:
            parts.append(f"removed({len(self.removed)})")
        if self.changed:
            parts.append(f"changed({len(self.changed)})")
        return "dep drift: " + ", ".join(parts)


def verify_dep_lock(
    lock_path: Path = _DEFAULT_LOCK_PATH,
    *,
    _pip_freeze_output: str | None = None,
) -> DepDriftResult:
    """Compare currently installed packages to requirements.lock.

    Returns DepDriftResult describing any drift. Never raises — on any error
    returns DepDriftResult(ok=False, ...) with the error in changed[].

    _pip_freeze_output: inject freeze text (tests). None → run pip freeze.
    """
    if not lock_path.exists():
        return DepDriftResult(
            ok=False,
            added=[],
            removed=[],
            changed=[f"lock file missing: {lock_path}"],
        )

    try:
        lock_pkgs = _parse_freeze(lock_path.read_text())
    except Exception as exc:
        return DepDriftResult(ok=False, added=[], removed=[], changed=[f"lock read error: {exc}"])

    if _pip_freeze_output is not None:
        env_text = _pip_freeze_output
    else:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "freeze"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                return DepDriftResult(
                    ok=False,
                    added=[],
                    removed=[],
                    changed=[f"pip freeze failed (rc={proc.returncode}): {proc.stderr[:200]}"],
                )
            env_text = proc.stdout
        except Exception as exc:
            return DepDriftResult(ok=False, added=[], removed=[], changed=[f"pip freeze error: {exc}"])

    try:
        env_pkgs = _parse_freeze(env_text)
    except Exception as exc:
        return DepDriftResult(ok=False, added=[], removed=[], changed=[f"freeze parse error: {exc}"])

    lock_names = set(lock_pkgs)
    env_names = set(env_pkgs)

    added = sorted(f"{n}=={env_pkgs[n]}" for n in env_names - lock_names)
    removed = sorted(f"{n}=={lock_pkgs[n]}" for n in lock_names - env_names)
    changed = sorted(
        f"{n}: lock={lock_pkgs[n]} env={env_pkgs[n]}"
        for n in lock_names & env_names
        if lock_pkgs[n] != env_pkgs[n]
    )

    ok = not (added or removed or changed)
    return DepDriftResult(ok=ok, added=added, removed=removed, changed=changed)


def _parse_freeze(text: str) -> dict[str, str]:
    """Parse pip freeze output → {normalised_name: version}.

    Normalises package names to lowercase with underscores (PEP 503 canonical form).
    Skips comment lines, blank lines, and -e / -r directives.
    """
    pkgs: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        if "==" in line:
            name, _, version = line.partition("==")
            pkgs[_normalise(name)] = version.strip()
    return pkgs


def _normalise(name: str) -> str:
    return name.strip().lower().replace("-", "_")
