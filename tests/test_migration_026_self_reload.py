"""tests/test_migration_026_self_reload.py — TDD for managed_self_reload ledger (Phase 25 Stage 1)."""
from __future__ import annotations

import os

import pytest

import anima.db as db


@pytest.fixture()
def _db(tmp_path):
    db.init(str(tmp_path / "test.db"))


class TestManagedSelfReloadLedger:
    def test_history_empty_initially(self, _db) -> None:
        assert db.list_self_reload_history() == []

    def test_record_then_list(self, _db) -> None:
        db.record_self_reload_outcome("OLDSHA", "NEWSHA", "committed")
        rows = db.list_self_reload_history()
        assert len(rows) == 1
        assert rows[0]["old_sha"] == "OLDSHA"
        assert rows[0]["new_sha"] == "NEWSHA"
        assert rows[0]["outcome"] == "committed"

    def test_list_returns_most_recent_first(self, _db) -> None:
        db.record_self_reload_outcome("SHA1", "SHA2", "committed")
        db.record_self_reload_outcome("SHA2", "SHA3", "resurrected")
        rows = db.list_self_reload_history()
        assert [r["outcome"] for r in rows] == ["resurrected", "committed"]

    def test_list_respects_limit(self, _db) -> None:
        for i in range(5):
            db.record_self_reload_outcome(f"SHA{i}", f"SHA{i+1}", "committed")
        rows = db.list_self_reload_history(limit=2)
        assert len(rows) == 2

    def test_rejects_invalid_outcome(self, _db) -> None:
        with pytest.raises(Exception):
            db.record_self_reload_outcome("OLDSHA", "NEWSHA", "not-a-real-outcome")
