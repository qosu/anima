#!/bin/bash
# rawos Phase 23F.3 boot deadman — I-UT8
# Runs at boot if /etc/rawos/unit-topology-deadman.armed exists.
# Healthy floor → disarm self. Unhealthy floor OR force-revert flag → revert + reboot.
set -uo pipefail

ARMED="/etc/rawos/unit-topology-deadman.armed"
REVERT="/etc/rawos/unit-topology-deadman.revert.sh"
FORCE_REVERT="/etc/rawos/unit-topology-deadman.force-revert"

echo "rawos-unit-topology-revert: armed — running boot health check"

# Drill mode: force-revert flag bypasses floor check (no need to break floor for testing)
if [[ -f "$FORCE_REVERT" ]]; then
    echo "FORCE-REVERT flag present — executing revert (drill)"
    rm -f "$FORCE_REVERT" "$ARMED"
    if [[ -f "$REVERT" ]]; then
        bash "$REVERT"
    fi
    systemctl disable rawos-unit-topology-revert.service --no-reload 2>/dev/null || true
    systemctl daemon-reload
    echo "Revert complete. Rebooting in 5s..."
    sleep 5
    reboot
    exit 0
fi

# Floor health check — canonical floor set (mirrors FLOOR_UNIT_SEED runtime members)
UNHEALTHY=0
declare -a FLOOR_CHECKS=("ssh.service" "rawos.service" "systemd-networkd.service")
for unit in "${FLOOR_CHECKS[@]}"; do
    if systemctl is-active --quiet "$unit" 2>/dev/null; then
        echo "  HEALTHY: $unit"
    else
        echo "  UNHEALTHY: $unit"
        UNHEALTHY=1
    fi
done

if [[ $UNHEALTHY -eq 0 ]]; then
    echo "All floor units healthy — disarming deadman"
    rm -f "$ARMED"
    systemctl disable rawos-unit-topology-revert.service --no-reload 2>/dev/null || true
    systemctl daemon-reload
    echo "rawos-unit-topology-revert: disarmed successfully"
    exit 0
fi

# Floor unhealthy — revert and reboot
echo "FLOOR UNHEALTHY — executing revert before reboot"
rm -f "$ARMED"
if [[ -f "$REVERT" ]]; then
    bash "$REVERT" && echo "Revert script executed OK" || echo "WARNING: revert script exit non-zero"
fi
systemctl disable rawos-unit-topology-revert.service --no-reload 2>/dev/null || true
systemctl daemon-reload
echo "Rebooting in 5s..."
sleep 5
reboot
