-- Migration 026: self-reload outcome ledger (Phase 25 Stage 1 — "The Ouroboros").
--
-- One row per execute_owner_self_reload() resolution, written by
-- boot_liveness_commit() at the NEW self's boot. Outcome is one of:
--   'committed'        — new_sha live + healthy, deadman disarmed
--   'resurrected'      — deadman fired, reverted to old_sha, old self resumed
--   'liveness_failed'  — new_sha live but probe never passed before deadline
--
-- This is a pure history/audit ledger — Stage 1 reads it only for the
-- `rawos selfreload status` CLI command. Stage 2 reads it as the
-- operator_track_record-equivalent graduation ledger for autonomous
-- self-reload (threshold = 3 consecutive 'committed' rows).
--
-- No FK to users: self-reload acts on the whole being, not a per-user
-- resource, and Stage 1 has no autonomous path (I-SR6).

PRAGMA user_version = 26;

CREATE TABLE IF NOT EXISTS managed_self_reload (
    id          TEXT    PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    old_sha     TEXT    NOT NULL,
    new_sha     TEXT    NOT NULL,
    outcome     TEXT    NOT NULL CHECK (outcome IN ('committed', 'resurrected', 'liveness_failed')),
    created_at  INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE INDEX IF NOT EXISTS idx_managed_self_reload_created_at
    ON managed_self_reload(created_at DESC);
