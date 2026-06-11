-- Migration 018: link rawos_commits to the origin repo + anomaly class
-- (Stage 3 of "Earned, Reversible Autonomy" —
-- see docs/plans/squishy-watching-stroustrup.md).
--
-- rawos_commits.workdir is the disposable per-run worktree path
-- (/root/.rawos-worktrees/<repo>-<ts>-<uuid>), removed once the SERVER_SCAN
-- run ends — it cannot be used to find the origin repo later. repo_root
-- (ServerAnomaly.affected_path / trigger_ctx["repo_root"]) and
-- anomaly_domain (ServerAnomaly.domain) are the origin repo path and
-- anomaly class, populated only for SERVER_SCAN commits, and let
-- _update_earned_autonomy_track_records find the most recent rawos/fix-*
-- branch+sha proposed for a given (repo, anomaly_domain).

PRAGMA user_version = 18;

ALTER TABLE rawos_commits ADD COLUMN repo_root TEXT;
ALTER TABLE rawos_commits ADD COLUMN anomaly_domain TEXT;

CREATE INDEX IF NOT EXISTS idx_rawos_commits_repo_domain
    ON rawos_commits(repo_root, anomaly_domain, created_at DESC);
