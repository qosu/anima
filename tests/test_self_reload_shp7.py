"""tests/test_self_reload_shp7.py — SHP.7 supply-chain hardening for self_reload.py.

Tests for:
  A. _verify_sha_ancestry() — unit tests (refuses ancestor/orphan, accepts descendant)
  B. preflight_stage ancestry integration — refuses non-descendant SHA end-to-end
  C. arm_and_swap audit chain — swap event appended before git reset
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

from anima.kernel.self_reload import (
    SELF_RELOAD_DEADMAN_UNIT,
    SelfReloadRefusalError,
    SelfReloadSnapshot,
    _verify_sha_ancestry,
    arm_and_swap,
    preflight_stage,
)


# ── Re-use fakes from test_self_reload.py ─────────────────────────────────────

class FakeResult:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    def __init__(self, responses: dict | None = None) -> None:
        self.responses = dict(responses or {})
        self.calls: list[tuple] = []

    def run(self, args: list[str], cwd: str) -> FakeResult:
        key = tuple(args)
        self.calls.append((key, cwd))
        return self.responses.get(key, FakeResult(returncode=0, stdout="", stderr=""))


class FakeWorktree:
    def __init__(self, path: str = "/fake/worktree") -> None:
        self.path = path

    def create(self, repo_path: str, sha: str) -> str:
        return self.path

    def remove(self, path: str) -> None:
        pass


class FakeSelfReloadDeadman:
    def __init__(self) -> None:
        self.armed: list = []
        self.disarmed: list = []

    def arm(self, unit: str, delay_s: int, revert_cmd: str) -> None:
        self.armed.append((unit, delay_s, revert_cmd))

    def disarm(self, unit: str) -> None:
        self.disarmed.append(unit)


class FakeExit:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def __call__(self, code: int) -> None:
        self.calls.append(code)


_REV_PARSE_HEAD = ("git", "rev-parse", "HEAD")
_MERGE_BASE_IS_ANCESTOR_OLD_NEW = ("git", "merge-base", "--is-ancestor", "OLDSHA", "NEWSHA")


def _runner(extra: dict | None = None) -> FakeRunner:
    base = {
        _REV_PARSE_HEAD: FakeResult(stdout="OLDSHA\n"),
        # Default: NEWSHA IS a descendant of OLDSHA (normal case)
        _MERGE_BASE_IS_ANCESTOR_OLD_NEW: FakeResult(returncode=0),
    }
    if extra:
        base.update(extra)
    return FakeRunner(base)


def _snapshot(**overrides) -> SelfReloadSnapshot:
    base = dict(
        old_sha="OLDSHA",
        new_sha="NEWSHA",
        state_id=str(uuid.uuid4()),
        armed_at=0.0,
        deadman_unit=SELF_RELOAD_DEADMAN_UNIT,
        migration_delta=[],
        venv_frozen_hash="hash",
    )
    base.update(overrides)
    return SelfReloadSnapshot(**base)


# ── A. _verify_sha_ancestry() unit tests ─────────────────────────────────────

class TestVerifyShaAncestry:
    """Unit tests for _verify_sha_ancestry() — imported directly from self_reload."""

    def test_descendant_sha_passes(self):
        """NEWSHA is a descendant of OLDSHA — must pass."""
        runner = FakeRunner({
            _REV_PARSE_HEAD: FakeResult(stdout="OLDSHA\n"),
            ("git", "merge-base", "--is-ancestor", "OLDSHA", "NEWSHA"): FakeResult(returncode=0),
        })
        # Must not raise
        _verify_sha_ancestry(runner, "/fake", "NEWSHA")

    def test_same_sha_as_head_passes(self):
        """new_sha == HEAD is a valid no-op reload — must pass without merge-base call."""
        runner = FakeRunner({
            _REV_PARSE_HEAD: FakeResult(stdout="SAMSHA\n"),
            # No merge-base response needed — short-circuit on same SHA
        })
        _verify_sha_ancestry(runner, "/fake", "SAMSHA")
        # Confirm no merge-base call was made
        merge_base_calls = [c for (c, _) in runner.calls if c[1] == "merge-base"]
        assert merge_base_calls == []

    def test_ancestor_sha_fails(self):
        """Loading an ancestor (parent) SHA is a rewind — must refuse."""
        runner = FakeRunner({
            _REV_PARSE_HEAD: FakeResult(stdout="NEWSHA\n"),
            ("git", "merge-base", "--is-ancestor", "NEWSHA", "OLDSHA"): FakeResult(returncode=1),
        })
        with pytest.raises(SelfReloadRefusalError, match="not a descendant"):
            _verify_sha_ancestry(runner, "/fake", "OLDSHA")

    def test_orphan_sha_fails(self):
        """An orphan commit (no common ancestry with HEAD) must be refused."""
        runner = FakeRunner({
            _REV_PARSE_HEAD: FakeResult(stdout="OLDSHA\n"),
            ("git", "merge-base", "--is-ancestor", "OLDSHA", "ORPHANSHA"): FakeResult(returncode=1),
        })
        with pytest.raises(SelfReloadRefusalError, match="not a descendant"):
            _verify_sha_ancestry(runner, "/fake", "ORPHANSHA")

    def test_error_message_includes_sha_prefixes(self):
        """Refusal message must include both new_sha prefix and HEAD prefix for diagnosability."""
        runner = FakeRunner({
            _REV_PARSE_HEAD: FakeResult(stdout="abcdef123456\n"),
            ("git", "merge-base", "--is-ancestor", "abcdef123456", "xyz999"): FakeResult(returncode=1),
        })
        with pytest.raises(SelfReloadRefusalError) as exc_info:
            _verify_sha_ancestry(runner, "/fake", "xyz999")
        msg = str(exc_info.value)
        assert "xyz999" in msg
        assert "abcdef1" in msg  # first 7 chars of HEAD


# ── B. preflight_stage ancestry integration ───────────────────────────────────

class TestPreflightAncestryIntegration:
    """Ancestry check must fire FIRST in preflight_stage before other checks."""

    def test_preflight_refuses_non_descendant_sha(self):
        """preflight_stage must refuse if ancestry check fails."""
        runner = _runner({
            _MERGE_BASE_IS_ANCESTOR_OLD_NEW: FakeResult(returncode=1),
        })
        with pytest.raises(SelfReloadRefusalError, match="not a descendant"):
            preflight_stage("NEWSHA", _source_root="/fake/repo", _runner=runner, _worktree=FakeWorktree())

    def test_preflight_passes_descendant_sha(self):
        """preflight_stage must proceed past ancestry check when new_sha is a descendant."""
        runner = _runner({
            _MERGE_BASE_IS_ANCESTOR_OLD_NEW: FakeResult(returncode=0),
        })
        snap = preflight_stage("NEWSHA", _source_root="/fake/repo", _runner=runner, _worktree=FakeWorktree())
        assert snap.new_sha == "NEWSHA"

    def test_preflight_ancestry_checked_before_migration_check(self):
        """Ancestry check must fire before migration check — fail fast on forged SHA."""
        order = []
        original_runner_cls = FakeRunner

        class OrderTrackingRunner:
            def __init__(self, responses):
                self._resp = responses
                self.calls = []

            def run(self, args, cwd):
                key = tuple(args)
                self.calls.append((key, cwd))
                if "merge-base" in key:
                    order.append("ancestry")
                    return FakeResult(returncode=1)  # fail ancestry
                if "diff" in key and "migrations/" in key:
                    order.append("migration")
                return FakeResult(returncode=0)

        runner = OrderTrackingRunner({})
        runner.responses = {}
        # monkeypatch _git_head
        import anima.kernel.self_reload as sr
        orig = sr._git_head
        sr._git_head = lambda r, cwd: "OLDSHA"
        try:
            with pytest.raises(SelfReloadRefusalError, match="not a descendant"):
                preflight_stage(
                    "NEWSHA",
                    _source_root="/fake/repo",
                    _runner=runner,
                    _worktree=FakeWorktree(),
                )
        finally:
            sr._git_head = orig

        # ancestry must appear; migration must NOT appear (short-circuited)
        assert "ancestry" in order
        assert "migration" not in order


# ── C. arm_and_swap audit chain ───────────────────────────────────────────────

class TestArmAndSwapAuditChain:
    """arm_and_swap must append a tamper-evident record to the audit chain."""

    def test_arm_and_swap_appends_self_reload_arm_event(self, tmp_path, monkeypatch):
        """arm_and_swap must call audit_chain.append('self_reload_arm', ...) before git reset."""
        import anima.kernel.audit_chain as ac
        appended: list[tuple[str, dict]] = []
        monkeypatch.setattr(ac, "append", lambda et, p: appended.append((et, dict(p))) or {})

        sd = FakeSelfReloadDeadman()
        fake_exit = FakeExit()
        runner = _runner()

        arm_and_swap(
            _snapshot(),
            _systemd=sd,
            _exit=fake_exit,
            _source_root="/fake",
            _runner=runner,
            _state_dir=str(tmp_path),
        )

        event_types = [et for (et, _) in appended]
        assert "self_reload_arm" in event_types

    def test_arm_and_swap_audit_record_contains_sha_fields(self, tmp_path, monkeypatch):
        """Audit record payload must include old_sha, new_sha, state_id, autonomous."""
        import anima.kernel.audit_chain as ac
        appended: list[tuple[str, dict]] = []
        monkeypatch.setattr(ac, "append", lambda et, p: appended.append((et, dict(p))) or {})

        sd = FakeSelfReloadDeadman()
        fake_exit = FakeExit()
        snap = _snapshot(old_sha="SHA_A", new_sha="SHA_B")

        arm_and_swap(
            snap,
            _systemd=sd,
            _exit=fake_exit,
            _source_root="/fake",
            _runner=_runner(),
            _state_dir=str(tmp_path),
        )

        arm_events = {et: p for (et, p) in appended if et == "self_reload_arm"}
        assert "self_reload_arm" in arm_events
        payload = arm_events["self_reload_arm"]
        assert payload["old_sha"] == "SHA_A"
        assert payload["new_sha"] == "SHA_B"
        assert payload["state_id"] == snap.state_id
        assert "autonomous" in payload

    def test_arm_and_swap_audit_failure_does_not_block_swap(self, tmp_path, monkeypatch):
        """If audit_chain.append raises, arm_and_swap must still proceed (fail-open)."""
        import anima.kernel.audit_chain as ac
        monkeypatch.setattr(ac, "append", lambda *a, **k: (_ for _ in ()).throw(IOError("disk full")))

        sd = FakeSelfReloadDeadman()
        fake_exit = FakeExit()

        # Must not raise — audit failure is non-fatal
        arm_and_swap(
            _snapshot(),
            _systemd=sd,
            _exit=fake_exit,
            _source_root="/fake",
            _runner=_runner(),
            _state_dir=str(tmp_path),
        )

        assert fake_exit.calls == [0]  # swap still happened

    def test_audit_record_written_before_git_reset(self, tmp_path, monkeypatch):
        """Audit record must be written BEFORE git reset (so it's present if reset fails)."""
        import anima.kernel.audit_chain as ac
        order: list[str] = []

        def _fake_append(et, p):
            order.append(f"audit:{et}")
            return {}

        monkeypatch.setattr(ac, "append", _fake_append)

        class OrderTrackingRunner:
            def __init__(self):
                self.responses = {
                    _REV_PARSE_HEAD: FakeResult(stdout="OLDSHA\n"),
                    _MERGE_BASE_IS_ANCESTOR_OLD_NEW: FakeResult(returncode=0),
                }
                self.calls = []

            def run(self, args, cwd):
                key = tuple(args)
                self.calls.append(key)
                if "reset" in key:
                    order.append("git_reset")
                return self.responses.get(key, FakeResult())

        sd = FakeSelfReloadDeadman()
        fake_exit = FakeExit()

        arm_and_swap(
            _snapshot(),
            _systemd=sd,
            _exit=fake_exit,
            _source_root="/fake",
            _runner=OrderTrackingRunner(),
            _state_dir=str(tmp_path),
        )

        assert "audit:self_reload_arm" in order
        assert "git_reset" in order
        audit_idx = order.index("audit:self_reload_arm")
        reset_idx = order.index("git_reset")
        assert audit_idx < reset_idx, "Audit record must precede git reset"
