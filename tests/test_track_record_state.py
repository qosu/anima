"""
Stage 3 — autonomy track-record state machine (pure logic, no I/O).

Covers kernel/track_record.py's _advance_state(): the per-scan-cycle update
to a (repo, anomaly_domain) track record, used to decide when a class
"graduates" from propose-only to auto-apply-with-rollback.
"""
from __future__ import annotations

from anima.kernel.track_record import GRADUATION_THRESHOLD, TrackRecordState, _advance_state


def test_not_merged_returns_state_unchanged():
    state = TrackRecordState(verified_successes=1, pending_since=100)

    result = _advance_state(
        state, anomaly_present=True, branch_merged=False,
        fix_branch="rawos/fix-a", fix_sha="aaa", now=200,
    )

    assert result == state


def test_merged_resolved_first_cycle_starts_pending_without_incrementing():
    state = TrackRecordState()

    result = _advance_state(
        state, anomaly_present=False, branch_merged=True,
        fix_branch="rawos/fix-a", fix_sha="aaa", now=100,
    )

    assert result.verified_successes == 0
    assert result.pending_since == 100
    assert result.last_fix_branch == "rawos/fix-a"
    assert result.last_outcome == "merged_pending_stability"
    assert result.graduated is False


def test_merged_resolved_second_consecutive_cycle_increments_verified_successes():
    state = TrackRecordState(pending_since=100, last_fix_branch="rawos/fix-a", last_fix_sha="aaa")

    result = _advance_state(
        state, anomaly_present=False, branch_merged=True,
        fix_branch="rawos/fix-a", fix_sha="aaa", now=200,
    )

    assert result.verified_successes == 1
    assert result.pending_since is None
    assert result.last_outcome == "merged_resolved"
    assert result.graduated is False


def test_merged_regressed_resets_pending_without_incrementing():
    state = TrackRecordState(
        verified_successes=2, pending_since=100,
        last_fix_branch="rawos/fix-a", last_fix_sha="aaa",
    )

    result = _advance_state(
        state, anomaly_present=True, branch_merged=True,
        fix_branch="rawos/fix-a", fix_sha="aaa", now=200,
    )

    assert result.verified_successes == 2
    assert result.pending_since is None
    assert result.last_outcome == "merged_regressed"
    assert result.graduated is False


def test_new_fix_branch_merged_while_previous_still_pending_restarts_tracking():
    # Previous fix (rawos/fix-a) was merged and resolved for 1 cycle (pending).
    # Before its 2nd confirming cycle, a DIFFERENT fix (rawos/fix-b) is merged
    # and also observed resolved. Tracking must restart for fix-b, not credit
    # fix-a's incomplete stability window.
    state = TrackRecordState(pending_since=100, last_fix_branch="rawos/fix-a", last_fix_sha="aaa")

    result = _advance_state(
        state, anomaly_present=False, branch_merged=True,
        fix_branch="rawos/fix-b", fix_sha="bbb", now=150,
    )

    assert result.verified_successes == 0
    assert result.pending_since == 150
    assert result.last_fix_branch == "rawos/fix-b"
    assert result.last_fix_sha == "bbb"


def test_graduates_after_reaching_threshold():
    assert GRADUATION_THRESHOLD == 3
    state = TrackRecordState(verified_successes=2)

    result = _advance_state(
        state, anomaly_present=False, branch_merged=True,
        fix_branch="rawos/fix-c", fix_sha="ccc", now=100,
    )
    assert result.verified_successes == 2  # first cycle: pending only
    assert result.graduated is False

    result = _advance_state(
        result, anomaly_present=False, branch_merged=True,
        fix_branch="rawos/fix-c", fix_sha="ccc", now=200,
    )
    assert result.verified_successes == 3
    assert result.graduated is True


def test_already_graduated_stays_graduated():
    state = TrackRecordState(verified_successes=GRADUATION_THRESHOLD, graduated=True)

    result = _advance_state(
        state, anomaly_present=True, branch_merged=False,
        fix_branch="rawos/fix-d", fix_sha="ddd", now=100,
    )

    assert result.graduated is True
