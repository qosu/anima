-- Migration 017: earned-autonomy track record (Stage 3 of
-- "Earned, Reversible Autonomy" — see docs/plans/squishy-watching-stroustrup.md).
--
-- One row per (user, repo, anomaly_domain), e.g.
-- (rawos-entity, /root/liveproof-agent, "service_failed:research-foundry.service").
-- A class graduates from propose-only to auto-apply-with-rollback only after
-- verified_successes reaches the graduation threshold defined in
-- rawos.kernel.track_record (currently 3) — never written by hand.

PRAGMA user_version = 17;

CREATE TABLE IF NOT EXISTS autonomy_track_record (
    id                  TEXT    PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id             TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    repo_root           TEXT    NOT NULL,
    anomaly_domain      TEXT    NOT NULL,
    verified_successes  INTEGER NOT NULL DEFAULT 0,
    graduated           INTEGER NOT NULL DEFAULT 0 CHECK (graduated IN (0, 1)),
    last_outcome        TEXT,
    last_fix_branch     TEXT,
    last_fix_sha        TEXT,
    pending_since       INTEGER,
    updated_at          INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE(user_id, repo_root, anomaly_domain)
);

CREATE INDEX IF NOT EXISTS idx_autonomy_track_record_lookup
    ON autonomy_track_record(user_id, repo_root, anomaly_domain);
