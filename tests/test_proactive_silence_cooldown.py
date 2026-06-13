"""tests/test_proactive_silence_cooldown.py — TDD for the SILENCE cooldown bug fix.

Root cause: _run_proactive_agent decides SILENCE → returns without recording
proactive_artifact → _is_goal_on_cooldown returns False on next 120s scan →
same goal re-fires every 120s → ~50M tokens/day burn.

Fix: record action_type="silence" artifact in the SILENCE branch so the cooldown
gate in _scan_once blocks the re-fire for GOAL_COOLDOWN_S=900 seconds.
"""
from __future__ import annotations

import hashlib
import os
import tempfile

import pytest

import rawos.db as db
import rawos.scheduler.proactive as proactive
from rawos.inference.intent_engine import InferredIntent
from rawos.models import User


class TestSilenceCooldownMechanism:
    """Unit: _record_proactive_artifact with action_type=silence enables _is_goal_on_cooldown."""

    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        db.init(os.path.join(self.tmp, "test.db"))
        self.user = db.create_user(User(
            email=f"silence-mech-{id(self)}-{os.getpid()}@test.com",
            password_hash=hashlib.sha256(b"pass").hexdigest(),
        ))

    def test_silence_artifact_enables_cooldown_gate(self):
        """_record_proactive_artifact with action_type=silence is recognised by _is_goal_on_cooldown."""
        uid = self.user.id
        cooldown_key = "IDLE_OPPORTUNITY:ui"

        assert not proactive._is_goal_on_cooldown(uid, cooldown_key)

        proactive._record_proactive_artifact(
            uid, "ui work on markdown project", 0.85,
            "", None, None,
            action_type="silence",
            cooldown_key=cooldown_key,
        )

        assert proactive._is_goal_on_cooldown(uid, cooldown_key)


class TestSilenceDecisionCooldown:
    """Integration: _run_proactive_agent SILENCE decision must record cooldown artifact."""

    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        db.init(os.path.join(self.tmp, "test.db"))
        self.user = db.create_user(User(
            email=f"silence-int-{id(self)}-{os.getpid()}@test.com",
            password_hash=hashlib.sha256(b"pass").hexdigest(),
        ))

    def _patch_db_writes(self, monkeypatch):
        """Patch DB writes that require FK-valid project/user rows not in temp DB."""
        from rawos.models import Intent, Agent, IntentStatus, AgentStatus
        import uuid

        def fake_create_intent(intent: Intent) -> Intent:
            intent.id = str(uuid.uuid4())
            return intent

        def fake_create_agent(agent: Agent) -> Agent:
            agent.id = str(uuid.uuid4())
            return agent

        def fake_update_intent(user_id, intent_id, **kw) -> None:
            pass

        monkeypatch.setattr(db, "create_intent", fake_create_intent)
        monkeypatch.setattr(db, "create_agent", fake_create_agent)
        monkeypatch.setattr(db, "update_intent", fake_update_intent)

    async def test_silence_sets_goal_cooldown(self, monkeypatch):
        """After _run_proactive_agent decides SILENCE, _is_goal_on_cooldown returns True.

        Without fix: SILENCE branch just returns → no artifact → cooldown gate
        returns False → same goal fires every 120s indefinitely (~50M tokens/day).

        After fix: SILENCE records artifact with cooldown_key → gate returns True for
        GOAL_COOLDOWN_S=900s → max ~96 runs/day instead of ~720.
        """
        import rawos.context.user_model as _um

        uid = self.user.id
        trigger_type = "IDLE_OPPORTUNITY"
        domain = "ui"
        # Must match _run_cooldown_key formula in _run_proactive_agent:
        # f"{trigger_type or 'unknown'}:{intent_obj.domain}"
        expected_cooldown_key = f"{trigger_type}:{domain}"

        monkeypatch.setattr(proactive, "_get_user_project", lambda u: ("proj-test", self.tmp))
        monkeypatch.setattr(proactive, "_evaluate_domain_confidence", lambda u, d: 1.0)
        monkeypatch.setattr(_um, "get_user_model", lambda u: {})
        self._patch_db_writes(monkeypatch)

        # Must be >=80 chars to pass the "result too short" guard in _run_proactive_agent.
        _SILENCE_RESPONSE = (
            "SILENCE Nothing to contribute at this time. The codebase looks clean "
            "and there are no obvious improvements needed right now."
        )

        async def _fake_loop(**kw) -> str:
            return _SILENCE_RESPONSE

        monkeypatch.setattr(proactive, "_run_proactive_loop", _fake_loop)

        intent = InferredIntent(
            goal="ui work on markdown project",
            domain=domain,
            confidence=0.85,
            source="idle",
        )

        assert not proactive._is_goal_on_cooldown(uid, expected_cooldown_key)

        await proactive._run_proactive_agent(uid, intent, trigger_type=trigger_type)

        # RED without fix: returns False (no artifact in SILENCE branch)
        # GREEN after fix: returns True
        assert proactive._is_goal_on_cooldown(uid, expected_cooldown_key), (
            "SILENCE decision must record proactive_artifact with cooldown_key so "
            "_is_goal_on_cooldown returns True — prevents re-fire every 120s"
        )

    async def test_silence_cooldown_key_matches_scan_once_key(self, monkeypatch):
        """The cooldown key recorded on SILENCE must match the key _scan_once checks.

        _scan_once uses: f"{trigger_type}:{intent_obj.domain}"
        _run_cooldown_key uses: f"{trigger_type or 'unknown'}:{intent_obj.domain}"

        When trigger_type is not None these are identical. This test verifies the
        happy path (trigger_type=IDLE_OPPORTUNITY) — the cost-critical scenario.
        """
        import rawos.context.user_model as _um

        uid = self.user.id
        trigger_type = "IDLE_OPPORTUNITY"
        domain = "code"
        scan_once_key = f"{trigger_type}:{domain}"  # what _scan_once checks

        monkeypatch.setattr(proactive, "_get_user_project", lambda u: ("proj-test", self.tmp))
        monkeypatch.setattr(proactive, "_evaluate_domain_confidence", lambda u, d: 1.0)
        monkeypatch.setattr(_um, "get_user_model", lambda u: {})
        self._patch_db_writes(monkeypatch)

        _SILENCE_RESPONSE = (
            "SILENCE Nothing to contribute at this time. The codebase looks clean "
            "and there are no obvious improvements needed right now."
        )

        async def _fake_loop(**kw) -> str:
            return _SILENCE_RESPONSE

        monkeypatch.setattr(proactive, "_run_proactive_loop", _fake_loop)

        intent = InferredIntent(
            goal="work on code quality", domain=domain, confidence=0.8, source="idle",
        )

        await proactive._run_proactive_agent(uid, intent, trigger_type=trigger_type)

        # The key _scan_once would check must be on cooldown after SILENCE
        assert proactive._is_goal_on_cooldown(uid, scan_once_key), (
            "Cooldown key recorded by _run_proactive_agent on SILENCE must match "
            "the key _scan_once checks — otherwise cooldown is silently ineffective"
        )


class TestComputeCooldownKey:
    """_compute_cooldown_key is the single source of truth for cooldown_key,
    used identically at the recording site (_run_proactive_agent) and the
    gating site (_scan_once). Divergence between the two formulas previously
    caused trigger_type=None goals (e.g. domain='ui') to bypass GOAL_COOLDOWN_S
    entirely: recorded key 'unknown:ui' never matched gate key 'None:ui'.
    """

    def test_explicit_trigger_type(self):
        assert proactive._compute_cooldown_key("IDLE_OPPORTUNITY", "code") == "IDLE_OPPORTUNITY:code"

    def test_none_trigger_type_falls_back_to_unknown(self):
        assert proactive._compute_cooldown_key(None, "ui") == "unknown:ui"

    def test_needs_attention_uses_calendar_uid(self):
        key = proactive._compute_cooldown_key("NEEDS_ATTENTION", "ui", trigger_ctx={"uid": "evt123"})
        assert key == "calendar_attention:evt123"

    def test_needs_attention_missing_trigger_ctx_does_not_crash(self):
        key = proactive._compute_cooldown_key("NEEDS_ATTENTION", "ui", trigger_ctx=None)
        assert key == "calendar_attention:"
