CHANGED: rawos/kernel/arch/linux.py | fix analyze_verify() — exclude dirs + non-unit files via _UNIT_EXTS frozenset | I-UT5 oracle now robust; dirs (.wants/.requires/.d/) caused exit non-zero → auto-restore fired (I-UT6 proven), then fixed
CHANGED: (23F.2 DRILL COMPLETE 2026-06-16) | live author+start+stop+delete on real systemd, all 15 checks pass | 23F.3 next = boot-graph + reboot, HUMAN-GATED
NEXT: 23F.3 human gate — SSH-session-2 + Hetzner console + Rescue sẵn, arm boot-deadman, commit boot-graph change benign, reboot, verify floor + deadman drill
