CHANGED: scripts/unit_topology_boot_deadman.sh (NEW) | boot deadman health check — floor probe + force-revert drill mode + auto-disarm | I-UT8 implementation
CHANGED: /etc/systemd/system/rawos-unit-topology-revert.service (LIVE, not in repo) | boot-graph deadman: enabled, armed, ConditionPathExists=armed flag | ready for 23F.3 reboot
CHANGED: /etc/rawos/unit-topology-deadman.{armed,revert.sh} (LIVE) | rawos-23f3-boottest enabled (boot-graph change), deadman armed | REBOOT PENDING human gate
NEXT: 23F.3C — human confirm session-2+console+rescue → arm transient deadman → grub-reboot 0 && reboot → post-reboot verify → force-revert drill
