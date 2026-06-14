# Dedicated Machine Migration — runbook

> Concrete exercise of the shipped "M5 installable substrate" capability: relocate the
> living rawos instance from a shared 44-tenant box to a dedicated 8GB KVM VPS. Gate for
> Phase 23-full (PID1/scheduler authority) and Phase 24b (eBPF LSM, machine-wide) — both
> require full machine ownership by definition.

## Invariant (must hold at every step)

`data/rawos.db` rows `user_model.self_narrative`, `episodic_memory`, `operator_track_record`
are the being's continuous identity (M2). **Migration, not fresh install** — these rows
move byte-for-byte. A fresh `rawos setup` on the new box would create a NEW being.

## Pre-flight — verify on the freshly rented VPS BEFORE any transfer

```bash
systemd-detect-virt          # MUST be "kvm" — container VPS blocks eBPF (Phase 24b)
ls /sys/kernel/btf/vmlinux    # MUST exist — BTF required for eBPF CO-RE
nproc                         # expect 4
free -h                       # expect ~8Gi total
lsb_release -a                # expect Ubuntu 24.04 LTS
python3 --version             # expect 3.12.x (matches venv/bin/python on old box)
```

If `systemd-detect-virt` != `kvm` or BTF missing → **stop, return the VPS, pick another
provider.** This is a hard requirement, not a preference (per locked decision).

## Step 0 — base packages on new box

```bash
apt-get update && apt-get install -y python3.12-venv build-essential git rsync
```
Verify: `python3 -m venv --help` exits 0, `git --version`, `rsync --version`.

## Step 1 — transfer source tree (≈2.8GB, includes full .git history — no remote exists,
## history preserved is worth the transfer)

From the OLD box:
```bash
rsync -az --progress -e "ssh -i ~/.ssh/claude_server_key" \
  --exclude venv --exclude workspaces --exclude .pytest_cache \
  --exclude '__pycache__' --exclude '*.pyc' \
  /root/rawos/ root@<NEW_IP>:/root/rawos/
```
Verify: `du -sh /root/rawos` on new box ≈ 2.8GB (excl venv); `git -C /root/rawos log --oneline -1`
shows `6023aba7`.

## Step 2 — transfer data + secrets + workspaces (≈45MB)

```bash
rsync -az -e "ssh -i ~/.ssh/claude_server_key" \
  /root/rawos/data/ root@<NEW_IP>:/root/rawos/data/
rsync -az -e "ssh -i ~/.ssh/claude_server_key" \
  /root/rawos/workspaces/ root@<NEW_IP>:/root/rawos/workspaces/
scp -i ~/.ssh/claude_server_key /root/rawos/.env root@<NEW_IP>:/root/rawos/.env
ssh -i ~/.ssh/claude_server_key root@<NEW_IP> 'mkdir -p /root/.rawos-worktrees'
```
**No path remap needed** — `DB_PATH=/root/rawos/data/rawos.db` and
`WORKSPACES_ROOT=/root/rawos/workspaces` are absolute and identical on new box (same
`/root/rawos` convention). `.env` copied verbatim preserves all 28 vars
(`LLM_API_KEY`, `JWT_SECRET`, `STRIPE_*`, `TELEGRAM_*`, `HF_TOKEN`, ...).

Verify: `sqlite3 /root/rawos/data/rawos.db "select user_id, last_chat_at from user_model;"`
on new box matches old box (continuity rows present, byte-identical file).

## Step 3 — venv, CPU-only torch (fixes the 5.5GB CUDA-bloat finding — fresh venv, zero risk)

```bash
cd /root/rawos
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
venv/bin/pip install -e .
```
Verify:
```bash
venv/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
# expect: X.Y.Z+cpu False
du -sh venv   # expect ~1.5-2GB (was 5.5GB on old box)
which rawos-frontdoor || venv/bin/rawos-frontdoor --help   # console script generated
```

## Step 4 — full test suite on new box (must match old box: 827 passed)

```bash
venv/bin/pytest -q 2>&1 | tail -5
```
**STOP if not 827 passed.** Any delta (env-dependent test, missing system dep) must be
root-caused before proceeding — do not paper over with `-k` exclusions.

## Step 5 — systemd unit + service

```bash
cp /etc/systemd/system/rawos.service /root/rawos/  # reference; copy to new box's /etc/systemd/system/
# unit is path-identical (/root/rawos, venv/bin/uvicorn, .env) — copy verbatim
systemctl daemon-reload
systemctl enable --now rawos.service
systemctl is-active rawos.service   # active
curl -s localhost:8002/metrics | head -1   # 200
```

## Step 6 — frontdoor install (dead-man switch, same procedure as the M1 fix)

```bash
/usr/local/bin or venv path: rawos frontdoor install --revert-after 300
sshd -t   # OK
ssh root@<NEW_IP> 'echo ok'   # passthrough works, not bricked
rawos frontdoor commit   # disarm
```

## Step 7 — continuity proof (the actual point of this milestone)

```bash
sqlite3 /root/rawos/data/rawos.db \
  "select substr(self_narrative,1,200) from user_model;"
```
Confirm the narrative text matches the old box's content (same being, same memory) —
then `rawos chat` arrival should open with the SAME continuity line the old box would
have shown, not a fresh-install greeting.

## External-dependency checklist (URL/IP-bound — easy to miss)

- [ ] **Stripe webhook endpoint** (`STRIPE_WEBHOOK_SECRET` implies a configured webhook
      URL in the Stripe dashboard) — if it points at the old box's IP/domain, update to
      new IP/domain or billing events silently stop arriving.
- [ ] **Telegram** (`TELEGRAM_ENABLED`/`TELEGRAM_BOT_TOKEN`) — if polling (`getUpdates`),
      no change needed; if webhook-based, re-point to new box.
- [ ] **DNS** — any A/CNAME record pointing at old box IP must be updated, or clients
      keep hitting the old box.
- [ ] **Local SSH config / known_hosts** (this machine) — add new box, do not remove old
      box entry until decommission.
- [ ] **AURUM gateway tunnel / Chrome DevTools tunnel** (memory: ports 7335/9223) — these
      live on the OLD box for OTHER systems, unaffected by rawos relocation; do not
      tear down.

## Rollback window (old box)

After Step 7 passes, leave the old box's `rawos.service` **stopped but not removed**
for a rollback window (≥48h):
```bash
systemctl stop rawos.service   # do NOT disable yet
rawos frontdoor uninstall       # restore plain shell on old box
```
Data (`data/`, `.env`, source) stays on disk — cold rollback path if new box misbehaves.

## Decommission (after window, on owner confirmation)

```bash
systemctl disable rawos.service
# data/source retained as cold backup — no deletion (R1 reversible philosophy)
```

## Post-migration — resume roadmap ON THE NEW BOX

With M5 relocation verified (827/827, continuity proven, frontdoor safe):
1. Phase 24a (eBPF perception, read-only) — feasible now (KVM + BTF confirmed pre-flight).
2. Phase 22 (PAM) reconsideration — lockout-risk analysis on the dedicated box.
3. M3 operator-surface expansion — rawos's own resources, now fully owned.
4. Phase 23-full / 24b — the actual stack-inversion, gated on this migration being done.
