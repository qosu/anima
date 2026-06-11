"""
rawos earned-autonomy track record — Stage 3 of "Earned, Reversible Autonomy"
(see docs/plans/squishy-watching-stroustrup.md).

A (repo, anomaly_domain) class starts untrusted (propose-only: a rawos/fix-*
branch + SIGNAL, human merges). Each time a human-merged fix stays resolved
across STABILITY_CYCLES_REQUIRED consecutive autonomous scan cycles, that
counts as one verified success. After GRADUATION_THRESHOLD verified successes,
the class graduates and becomes eligible for reversible_apply (Stage 3's
auto-apply-with-rollback) — gated additionally by
settings.autonomy_auto_apply_enabled (operator on/off switch for first
rollout).

This module is split in two halves:
  - _advance_state(): pure state transition, no I/O — fully unit-testable.
  - get_track_record() / update_track_record() / is_branch_merged(): I/O
    (sqlite + git), thin wrappers around _advance_state().
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace

import rawos.db as db
from rawos.kernel.sandbox import SandboxError, run_bash

log = logging.getLogger("rawos.kernel.track_record")

GRADUATION_THRESHOLD = 3
_GIT_TIMEOUT_S = 30


@dataclass(frozen=True)
class TrackRecordState:
    verified_successes: int = 0
    graduated: bool = False
    last_outcome: str | None = None
    last_fix_branch: str | None = None
    last_fix_sha: str | None = None
    pending_since: int | None = None


def _advance_state(
    state: TrackRecordState,
    *,
    anomaly_present: bool,
    branch_merged: bool,
    fix_branch: str | None,
    fix_sha: str | None,
    now: int,
) -> TrackRecordState:
    """Compute the next track-record state for one scan cycle.

    See module docstring for the earned-ladder rules. Only called when
    branch_merged is True does the state ever change — an unmerged proposal
    is still propose-only and contributes nothing to the track record yet.
    """
    if not branch_merged:
        return state

    if anomaly_present:
        # Merged fix did not (or no longer) resolves the anomaly: reset any
        # in-progress stability window. Per plan, this does not penalise
        # verified_successes already earned by prior, different fixes.
        return replace(
            state,
            pending_since=None,
            last_outcome="merged_regressed",
            last_fix_branch=fix_branch,
            last_fix_sha=fix_sha,
        )

    # Merged and the anomaly is currently absent (resolved).
    if state.pending_since is None or state.last_fix_branch != fix_branch:
        # First cycle observing this fix_branch merged+resolved — start (or
        # restart, if a different branch merged mid-window) the
        # STABILITY_CYCLES_REQUIRED=2 confirmation window.
        return replace(
            state,
            pending_since=now,
            last_fix_branch=fix_branch,
            last_fix_sha=fix_sha,
            last_outcome="merged_pending_stability",
        )

    verified = state.verified_successes + 1
    return replace(
        state,
        verified_successes=verified,
        graduated=state.graduated or verified >= GRADUATION_THRESHOLD,
        pending_since=None,
        last_outcome="merged_resolved",
    )


def _row_to_state(row) -> TrackRecordState:
    return TrackRecordState(
        verified_successes=row["verified_successes"],
        graduated=bool(row["graduated"]),
        last_outcome=row["last_outcome"],
        last_fix_branch=row["last_fix_branch"],
        last_fix_sha=row["last_fix_sha"],
        pending_since=row["pending_since"],
    )


def get_track_record(user_id: str, repo_root: str, anomaly_domain: str) -> TrackRecordState:
    """Return the current track-record state, or a fresh untrusted one if none exists."""
    with db._conn() as conn:
        row = conn.execute(
            """SELECT verified_successes, graduated, last_outcome,
                      last_fix_branch, last_fix_sha, pending_since
               FROM autonomy_track_record
               WHERE user_id = ? AND repo_root = ? AND anomaly_domain = ?""",
            (user_id, repo_root, anomaly_domain),
        ).fetchone()
    if row is None:
        return TrackRecordState()
    return _row_to_state(row)


def update_track_record(
    user_id: str,
    repo_root: str,
    anomaly_domain: str,
    *,
    anomaly_present: bool,
    branch_merged: bool,
    fix_branch: str | None,
    fix_sha: str | None,
    now: int,
) -> TrackRecordState:
    """Advance and persist the track record for one scan cycle. Returns the new state."""
    current = get_track_record(user_id, repo_root, anomaly_domain)
    new = _advance_state(
        current, anomaly_present=anomaly_present, branch_merged=branch_merged,
        fix_branch=fix_branch, fix_sha=fix_sha, now=now,
    )
    if new == current:
        return new

    with db._conn() as conn:
        conn.execute(
            """INSERT INTO autonomy_track_record
                   (user_id, repo_root, anomaly_domain, verified_successes,
                    graduated, last_outcome, last_fix_branch, last_fix_sha,
                    pending_since, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, repo_root, anomaly_domain) DO UPDATE SET
                   verified_successes = excluded.verified_successes,
                   graduated          = excluded.graduated,
                   last_outcome       = excluded.last_outcome,
                   last_fix_branch    = excluded.last_fix_branch,
                   last_fix_sha       = excluded.last_fix_sha,
                   pending_since      = excluded.pending_since,
                   updated_at         = excluded.updated_at""",
            (
                user_id, repo_root, anomaly_domain, new.verified_successes,
                int(new.graduated), new.last_outcome, new.last_fix_branch,
                new.last_fix_sha, new.pending_since, now,
            ),
        )
    if new.graduated and not current.graduated:
        log.info(
            "autonomy: class graduated repo=%s domain=%s after %d verified successes",
            repo_root, anomaly_domain, new.verified_successes,
        )
    return new


async def is_branch_merged(repo_path: str, sha: str) -> bool:
    """True iff `sha` is an ancestor of repo_path's default branch (origin/HEAD).

    Returns False (not merged) on any git error — a repo that cannot be
    inspected is treated as "not yet merged", never as "merged".
    """
    try:
        default = await run_bash("git rev-parse --abbrev-ref origin/HEAD", repo_path)
    except SandboxError:
        return False
    if default.exit_code != 0:
        return False
    default_ref = default.stdout.strip()
    if not default_ref:
        return False

    try:
        result = await run_bash(f"git merge-base --is-ancestor {sha} {default_ref}", repo_path)
    except SandboxError:
        return False
    return result.exit_code == 0
