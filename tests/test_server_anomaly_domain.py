"""
Stage 3 — ServerAnomaly.domain: the canonical (kind[:service]) string used
to key autonomy_track_record rows. Must match across to_trigger_ctx() (used
when recording rawos_commits.anomaly_domain) and _run_autonomous_scan's
cooldown/track-record lookups, or Stage 3's track-record wiring silently
never matches a row.
"""
from __future__ import annotations

from rawos.context.server_scanner import ServerAnomaly


def test_domain_includes_service_when_present():
    anomaly = ServerAnomaly(
        kind="service_failed", affected_path="/root/some-repo",
        service="foo.service", detail="d", last_log="", severity=8,
    )
    assert anomaly.domain == "service_failed:foo.service"


def test_domain_is_kind_only_when_no_service():
    anomaly = ServerAnomaly(
        kind="disk_critical", affected_path="/",
        service="", detail="d", last_log="", severity=9,
    )
    assert anomaly.domain == "disk_critical"


def test_to_trigger_ctx_includes_domain():
    anomaly = ServerAnomaly(
        kind="service_failed", affected_path="/root/some-repo",
        service="foo.service", detail="d", last_log="", severity=8,
    )
    assert anomaly.to_trigger_ctx()["domain"] == "service_failed:foo.service"
