OBJECTIVE: rawos gains reversible, owner-approved write authority over non-root-critical pam.d files on 167.233.44.121 without any path — autonomous or buggy — to lockout of the only account on the machine (root, uid=0).

INVARIANTS:

I1 SELF-PROTECTED FLOOR:
  _SELF_PROTECTED_PAM_FILES must contain every pam.d file present on this box at
  Phase 22 design-pass approval (sshd, common-auth, common-account, common-password,
  common-session, common-session-noninteractive, su, sudo, sudo-i, login, runuser,
  runuser-l, chfn, chpasswd, chsh, passwd, newusers, other, atd, cron, vmtoolsd).
  PamFileEdit construction raises PamRefusalError for any target in this set.
  This check runs at construction, not at runtime gate, and cannot be bypassed by any
  flag, graduation state, or owner-approved path.
  LOCKOUT VECTOR: write to common-auth or sshd → root SSH pubkey auth denied →
    total permanent lockout; no fallback account exists (root is the only account).

I2 BREAK-GLASS PREREQUISITE:
  No pam.d file on 167.233.44.121 may be written by any rawos code path unless a
  non-root recovery account with independent SSH pubkey access is verified reachable.
  Verification = `ssh -i recovery_key rawos-recovery@167.233.44.121 sudo true` exits 0
  from a session outside rawos. If verification fails at activation time, raise
  PamInstallError and do not proceed.
  LOCKOUT VECTOR: deadman timer misfires (systemd degraded, disk full, revert cmd error)
    → Layer 1 gone → no Layer 2 fallback → operator without KVM locked out permanently.

I3 DEADMAN ALWAYS ARMED BEFORE WRITE:
  install_pam_edit_with_deadman must call arm() and confirm the systemd-run timer unit
  exists BEFORE calling apply(). If arm() raises or the timer unit is not found in
  `systemctl list-timers`, raise PamInstallError and do not apply the change.
  LOCKOUT VECTOR: pam.d written without timer → validate() fails → no auto-revert path
    → broken auth persists until human intervenes via KVM.

I4 REVERT RUNS OUTSIDE PAM AUTH-PATH:
  The command invoked by the deadman timer (`rawos pam _revert <snapshot_id>`) must
  execute as a systemd transient unit launched from the already-authenticated systemd
  daemon (uid=0, not via SSH). The revert command must not call any subprocess that
  re-authenticates through the PAM stack being reverted.
  LOCKOUT VECTOR: PAM broken → SSH probe (revert path) traverses broken PAM →
    revert command blocks → deadman fires but cannot restore → lockout.

I5 ORACLE IS LIVE-AUTH PROBE, NOT SYNTACTIC:
  validate() returns True only when:
    ssh -i /root/.rawos-pam-backups/probe_key \
        -o ControlMaster=no -o ControlPath=none \
        -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
        root@127.0.0.1 true
  exits 0. The probe key is a dedicated on-box ED25519 key (authorized_keys:
  `restrict <pubkey> rawos-pam-probe@127.0.0.1`) that cannot be used for anything
  except authenticated connections. A passing pamtester result with a failing probe
  must return validate()=False and trigger restore().
  pamtester is a pre-flight syntactic check only, run before the live-auth probe.
  LOCKOUT VECTOR: pamtester passes but pam_access/pam_exec rule blocks pubkey path →
    commit() fires → deadman disarmed → auth broken permanently.

I6 PROBE KEY INDEPENDENCE:
  verify() must use ONLY the dedicated restricted probe key at
  /root/.rawos-pam-backups/probe_key — not the operator's personal SSH key, not any
  agent-forwarded key. The probe sends "true" as the SSH command argument, which
  triggers the frontdoor PASSTHROUGH branch before any health/token check, making
  the probe robust even when rawos.service is unhealthy.
  authorized_keys entry for the probe key must include the "restrict" option
  (disables port forwarding, agent forwarding, X11, pty). The probe opens a fresh
  TCP connection (ControlMaster=no, ControlPath=none) per verify() call.
  No operator lifeline session is required — the probe is fully autonomous.
  LOCKOUT VECTOR: probe falls back to operator's personal key or forwarded agent →
    oracle unreliable (depends on unrelated agent state) → PAM changes may be
    committed when auth is actually broken.

I7 NO AUTONOMOUS PAM WRITE PATH:
  No function named operate_on_pam() or equivalent exists. No graduation threshold
  leads to auto-apply of any pam.d change. No scheduled task, cron, or autonomous
  loop may call any PAM write function. The sole execution path for pam.d writes is
  execute_approved_pam_edit(), invokable only by an authenticated owner action in an
  active session (which also satisfies I6 by definition).
  LOCKOUT VECTOR: graduated auto-apply fires without operator present → no lifeline
    session → oracle cannot run → if validate() falsely passes → lockout;
    OR if rollback needed → no operator session means no clean rollback proof.

I8 ZERO PAM WRITES DURING DESIGN PASS:
  No file under /etc/pam.d/ on 167.233.44.121 is modified by any rawos code path
  during Phase 22 design-pass. After design-pass completion, `git status` on the box
  must show only `docs/phase22_pam_safety_floor.md` and `docs/phase22_pam_invariants.md`
  as new files; nothing else modified; `git diff` on all tracked files empty.
  LOCKOUT VECTOR: premature write before safety floor active → no guaranteed revert
    path → design-pass defeats its own stated purpose.

I9 SNAPSHOT STORED OUTSIDE DB:
  PamSnapshot prior_content must be written to `/root/.rawos-pam-backups/<uuid>` as a
  raw file, not to rawos.db. The restore path (both deadman revert and Layer 2 manual
  restore) must work when rawos.service is stopped and rawos.db is inaccessible.
  LOCKOUT VECTOR: snapshot in DB → PAM broken → rawos.service unhealthy → DB
    connection refused → deadman fires → revert cannot read snapshot → restore fails.
