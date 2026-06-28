"""anima/kernel/bpf_lsm.py — Phase 24B: eBPF LSM machine-wide MAC.

Design: mechanism/policy separation (Tetragon/Falco/Cilium model).
  Engine  = static BPF LSM bytecode, built OFF-BOX (CI clang+libbpf-dev),
            CO-RE-portable, checksum-pinned (I-LSM11), immutable on prod.
  Policy  = BPF maps written by rawos at runtime — denylist, protected-comm,
            mode-flag. Being authors its policy; CANNOT rewrite enforcement bytecode.
  Floor   = {sshd,systemd,holder,rawos,git,...} compiled into engine bytecode,
            checked BEFORE any map lookup (I-LSM5). Policy-map cannot override floor.

Invariants enforced here:
  I-LSM2  — unpinned link: holder death = kernel auto-detach, no reboot needed.
  I-LSM4  — audit-first: default mode="audit", promote enforce = 1 map write.
  I-LSM5  — floor compiled into engine + rejected at build_policy() (double-guard).
  I-LSM7  — heartbeat deadman: BpfLsmSupervisor sends periodic heartbeat to holder.
  I-LSM10 — fail-fast at boot: validate_boot_config() raises if inconsistent state.
  I-LSM11 — fail-closed integrity: _verify_artifact() rejects sha256 mismatch.
  I-LSM12 — dormant on ship: bpf_lsm_enabled=False, no enforce unless fully gated.

24B.0 ships ALL these invariants in pure-Python dormant form (holder = _NullHolderClient,
no BPF attach, no GRUB change). Real holder spawning deferred to maintenance-window
gates 24B.1–24B.4 (human-gated, never autonomous).
"""
from __future__ import annotations

import abc
import asyncio
import dataclasses
import hashlib
import os
import re
from typing import final

# ---------------------------------------------------------------------------
# Kernel-path singletons — monkeypatchable by tests (mirror landlock.py)
# ---------------------------------------------------------------------------
_LSM_ACTIVE_PATH: str = "/sys/kernel/security/lsm"
_BPFFS_PATH: str = "/sys/fs/bpf"
_BTF_PATH: str = "/sys/kernel/btf/vmlinux"

# Mutable cache so supported() does not re-read /proc every call.
# Monkeypatch directly in tests (tests/test_bpf_lsm.py pattern).
_support_cache: bool | None = None

# ---------------------------------------------------------------------------
# Floor — compiled into engine bytecode AND enforced here at policy-build time
# (I-LSM5 double-guard).
# Linux `comm` fields are truncated at 15 chars; names longer than 15 must use
# their truncated form so the BPF engine's string compare is consistent.
# ---------------------------------------------------------------------------
FLOOR_COMM: frozenset[str] = frozenset({
    # Operator access — never deny or machine is bricked.
    "sshd",
    # PID1 — never deny or boot dies.
    "systemd",
    # Login stack — deny → operator locked out.
    "login",
    "getty",
    "agetty",
    "su",
    "sudo",
    "unix_chkpwd",
    # Holder daemon itself (truncated to 15: "rawos-bpf-lsm-h").
    # The holder must never self-deny; floor-protecting it prevents an
    # enforcement-paradox where the LSM program that *implements* enforcement
    # is itself denied by enforcement.
    "rawos-bpf-lsm-h",
    # rawos being process.
    "rawos",
    # git plumbing — self-reload and code-pull depend on these.
    "git",
    "git-remote-http",
    "git-remote-htt",  # truncated 15-char form of git-remote-https
})

_VALID_MODES: frozenset[str] = frozenset({"audit", "enforce"})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class BpfLsmError(Exception):
    """Base exception for all BPF LSM errors."""


class BpfLsmUnsupportedError(BpfLsmError):
    """Raised when BPF LSM is not available on this host.

    Concrete reasons: `bpf` absent from /sys/kernel/security/lsm (needs
    `lsm=…,bpf` GRUB cmdline + reboot, Phase 24B.1), BTF missing, bpffs
    not mounted. All conditions are required simultaneously for full support.
    """


class BpfLsmIntegrityError(BpfLsmError):
    """Raised when a checksummed artifact fails sha256 verification (I-LSM11)."""


# ---------------------------------------------------------------------------
# Policy dataclass — frozen, built by build_policy() with floor guard
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True, slots=True)
class Policy:
    """Immutable policy snapshot sent to the holder's BPF maps.

    deny_comm      — process comm names to deny (FLOOR_COMM intersection rejected).
    protected_comm — extra names added to floor for this operator session (additive,
                     beyond the floor compiled into engine bytecode).
    mode           — "audit" (log-only, no deny) or "enforce" (active deny).
    """

    deny_comm: tuple[str, ...]
    protected_comm: tuple[str, ...]
    mode: str


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------
def supported() -> bool:
    """Return True iff this host can run BPF LSM enforcement.

    Requirements (all must hold):
      1. `bpf` appears in /sys/kernel/security/lsm (active LSM list).
      2. /sys/kernel/btf/vmlinux exists and is non-empty (CO-RE relocation).
      3. /sys/fs/bpf is a readable directory (bpffs mounted).

    Result is cached in _support_cache after first call. Tests monkeypatch
    _support_cache directly to bypass filesystem access.
    """
    global _support_cache
    if _support_cache is not None:
        return _support_cache

    try:
        lsm_text = open(_LSM_ACTIVE_PATH).read().strip()
        active_modules = {m.strip() for m in lsm_text.split(",")}
        if "bpf" not in active_modules:
            _support_cache = False
            return False

        # BTF must exist and be non-empty (empty file = stripped kernel, CO-RE fails).
        btf_size = os.path.getsize(_BTF_PATH) if os.path.isfile(_BTF_PATH) else 0
        if btf_size == 0:
            _support_cache = False
            return False

        # bpffs must be a readable directory.
        if not os.path.isdir(_BPFFS_PATH):
            _support_cache = False
            return False

        _support_cache = True
        return True
    except OSError:
        _support_cache = False
        return False


# ---------------------------------------------------------------------------
# Boot validation — I-LSM10 fail-fast
# ---------------------------------------------------------------------------
def validate_boot_config(*, enabled: bool, mode: str) -> None:
    """Fail-fast at rawos lifespan startup (mirrors landlock.validate_boot_config).

    Called unconditionally during lifespan even when enabled=False so mode
    typos in config are caught before enforcement is ever attempted.

    Rules:
      - enabled=False  → noop (I-LSM12: dormant ship).
      - enabled=True, invalid mode → BpfLsmError.
      - enabled=True, unsupported  → BpfLsmUnsupportedError.
      - enabled=True, valid mode, supported → noop (OK).
    """
    if not enabled:
        return

    if mode not in _VALID_MODES:
        raise BpfLsmError(
            f"bpf_lsm_mode={mode!r} invalid; must be one of {sorted(_VALID_MODES)}"
        )

    if not supported():
        raise BpfLsmUnsupportedError(
            "bpf_lsm_enabled=True but BPF LSM not available on this host. "
            "Requires `lsm=…,bpf` in GRUB cmdline + reboot (Phase 24B.1). "
            f"Active LSM list: {_read_active_lsm_raw()!r}. "
            f"BTF present: {os.path.isfile(_BTF_PATH)}. "
            f"bpffs mounted: {os.path.isdir(_BPFFS_PATH)}."
        )


def _read_active_lsm_raw() -> str:
    """Read raw /sys/kernel/security/lsm for diagnostics; never raises."""
    try:
        return open(_LSM_ACTIVE_PATH).read().strip()
    except OSError as exc:
        return f"<unreadable: {exc}>"


# ---------------------------------------------------------------------------
# LSM cmdline composer — pure function, I-LSM9 GRUB safety
# ---------------------------------------------------------------------------
def compose_lsm_cmdline(active_list: str) -> str:
    """Compose the `lsm=` GRUB cmdline value for the experimental entry.

    Takes the *exact* observed active LSM list (from /sys/kernel/security/lsm
    or verified boot log) and appends `bpf`. Pure function — never writes files.

    Invariant (I-LSM9): entry 0 must remain pristine. This function only
    COMPUTES the string; caller is responsible for limiting its use to the
    custom `--id rawos-bpf-lsm` entry (never entry 0).

    Raises BpfLsmError if:
      - active_list is empty or whitespace-only.
      - `bpf` is already present (idempotency guard: double-append corrupts cmdline).
    """
    stripped = active_list.strip()
    if not stripped:
        raise BpfLsmError(
            "active_list is empty; cannot compose lsm= cmdline. "
            "Read /sys/kernel/security/lsm on the target host first."
        )

    modules = [m.strip() for m in stripped.split(",")]
    if "bpf" in modules:
        raise BpfLsmError(
            f"`bpf` already present in active_list={active_list!r}. "
            "Calling compose_lsm_cmdline on an already-composed string would "
            "produce a duplicate entry and corrupt the lsm= cmdline."
        )

    return ",".join(modules + ["bpf"])


# ---------------------------------------------------------------------------
# Artifact integrity — I-LSM11 fail-closed
# ---------------------------------------------------------------------------
def _verify_artifact(path: str, expected_sha256: str) -> None:
    """Verify a prebuilt artifact's sha256 checksum; raise if mismatch.

    Raises BpfLsmIntegrityError on mismatch or FileNotFoundError on missing file.
    Never returns silently on mismatch — fail-closed (I-LSM11).
    """
    try:
        with open(path, "rb") as fh:
            actual = hashlib.sha256(fh.read()).hexdigest()
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise BpfLsmError(f"Cannot read artifact {path!r}: {exc}") from exc

    if actual != expected_sha256:
        raise BpfLsmIntegrityError(
            f"Artifact integrity check FAILED for {path!r}.\n"
            f"  expected sha256: {expected_sha256}\n"
            f"  actual   sha256: {actual}\n"
            "Refusing to load: tampered or mismatched artifact (I-LSM11)."
        )


# ---------------------------------------------------------------------------
# Floor guard — I-LSM5 (Python-side double-guard, engine-side baked in bytecode)
# ---------------------------------------------------------------------------
def is_protected(comm: str) -> bool:
    """Return True iff comm is a floor process that enforcement must never deny."""
    return comm in FLOOR_COMM


def build_policy(
    *,
    deny_comm: tuple[str, ...] | list[str],
    protected_comm: tuple[str, ...] | list[str],
    mode: str,
) -> Policy:
    """Construct a validated Policy; raise if it would violate invariants.

    I-LSM5 double-guard: rejects deny_comm that intersects FLOOR_COMM.
    Even in `enforce` mode the engine's floor bytecode would never execute
    the deny, but we reject at build-time to catch misconfiguration early
    and surface a clear error rather than a silent no-op.

    Raises BpfLsmError on:
      - any deny_comm member that is in FLOOR_COMM.
      - invalid mode (not in {"audit", "enforce"}).
    """
    deny_t = tuple(deny_comm)
    protected_t = tuple(protected_comm)

    if mode not in _VALID_MODES:
        raise BpfLsmError(
            f"Invalid mode={mode!r}; must be one of {sorted(_VALID_MODES)}."
        )

    floor_violations = frozenset(deny_t) & FLOOR_COMM
    if floor_violations:
        raise BpfLsmError(
            f"Policy deny_comm intersects FLOOR_COMM (I-LSM5 violation): "
            f"{sorted(floor_violations)}. Floor processes can NEVER be denied. "
            "Remove them from deny_comm."
        )

    return Policy(deny_comm=deny_t, protected_comm=protected_t, mode=mode)


# ---------------------------------------------------------------------------
# GRUB custom entry composer — pure function, I-LSM9
# ---------------------------------------------------------------------------
_UUID_RE = re.compile(r"root=UUID=([0-9a-f-]+)", re.IGNORECASE)


def compose_grub_custom_entry(
    base_cmdline: str,
    lsm_cmdline: str,
    kernel_ver: str,
) -> str:
    """Emit a complete /etc/grub.d/40_custom `menuentry` stanza.

    Uses `--id rawos-bpf-lsm` (NOT an index) so grub-reboot by id is stable
    even when kernels are added/removed (I-LSM9).

    The emitted entry clones the given base_cmdline (from known-good entry 0)
    and appends lsm_cmdline as a separate cmdline token. The root UUID is
    extracted from base_cmdline and used in the `search` directive.

    This function is PURE and does NOT write any files. Writing to
    /etc/grub.d/40_custom and running `update-grub` is a human-gated step
    (Phase 24B.1 maintenance window).

    Raises BpfLsmError if base_cmdline does not contain `root=UUID=…`.
    """
    uuid_match = _UUID_RE.search(base_cmdline)
    if not uuid_match:
        raise BpfLsmError(
            f"base_cmdline does not contain `root=UUID=…`: {base_cmdline!r}. "
            "Cannot construct search/linux stanzas without the root UUID."
        )
    root_uuid = uuid_match.group(1)

    # Compose the full linux cmdline: base args + lsm override.
    # lsm= must come AFTER all other cmdline tokens so it takes effect
    # (kernel processes cmdline left-to-right; last lsm= wins).
    full_cmdline = f"{base_cmdline} {lsm_cmdline}"

    entry = (
        f'menuentry "rawos BPF LSM (experimental, one-shot)" --id rawos-bpf-lsm {{\n'
        f"    search --no-floppy --fs-uuid --set=root {root_uuid}\n"
        f"    linux   /boot/vmlinuz-{kernel_ver} {full_cmdline}\n"
        f"    initrd  /boot/initrd.img-{kernel_ver}\n"
        f"}}\n"
    )
    return entry


# ---------------------------------------------------------------------------
# Holder client ABC + NullHolderClient (dormant implementation)
# ---------------------------------------------------------------------------
class BpfLsmHolderClient(abc.ABC):
    """Abstract control-plane client for the rawos-bpf-lsm-holder daemon.

    In 24B.0 (dormant), _NullHolderClient is used — all methods are no-ops.
    Post-24B.1 (when the holder binary ships and lsm= is in GRUB cmdline),
    _SocketHolderClient talks to the holder over a unix socket.
    """

    @abc.abstractmethod
    async def heartbeat(self) -> None:
        """Send a liveness ping to the holder (I-LSM7)."""

    @abc.abstractmethod
    async def flip_mode(self, mode: str) -> None:
        """Flip the mode BPF map between 'audit' and 'enforce' (I-LSM4)."""

    @abc.abstractmethod
    async def update_policy(self, policy: Policy) -> None:
        """Push a new policy snapshot to the holder's BPF maps."""

    @abc.abstractmethod
    async def detach(self) -> None:
        """Request graceful detach (holder releases bpf_link, exits cleanly)."""


_HOLDER_SOCK_PATH: str = "/run/rawos-bpf-lsm-holder.sock"


class _SocketHolderClient(BpfLsmHolderClient):
    """Unix-socket control client for the rawos-bpf-lsm-holder daemon (post-24B.1).

    Sends heartbeat/mode/detach commands over a unix stream socket.
    Each call opens a new connection (holder is simple, connections are brief).
    Socket I/O is blocking, run in executor to avoid blocking the event loop.
    Connection failure raises — BpfLsmSupervisor.run() catches and continues
    (I-LSM7: holder's own deadman handles sustained silence).
    """

    def __init__(self, sock_path: str = _HOLDER_SOCK_PATH) -> None:
        self._sock_path = sock_path

    def _send(self, cmd: str) -> None:
        import socket as _socket
        with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as s:
            s.settimeout(5.0)
            s.connect(self._sock_path)
            s.sendall((cmd + chr(10)).encode())
            s.recv(64)  # consume response

    async def heartbeat(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send, "heartbeat")

    async def flip_mode(self, mode: str) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send, f"mode {mode}")

    async def update_policy(self, policy: "Policy") -> None:
        pass  # TODO: deny_comm map updates via socket (24B.3+)

    async def detach(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send, "detach")


@final
class _NullHolderClient(BpfLsmHolderClient):
    """No-op holder client used when bpf_lsm_enabled=False (24B.0 dormant).

    All methods are silently no-ops. The supervisor uses this client so
    the heartbeat loop runs but has nothing to drive until a real
    _SocketHolderClient is wired in post-24B.1.
    """

    async def heartbeat(self) -> None:
        pass

    async def flip_mode(self, mode: str) -> None:
        pass

    async def update_policy(self, policy: Policy) -> None:
        pass

    async def detach(self) -> None:
        pass


# ---------------------------------------------------------------------------
# BpfLsmSupervisor — rawos-side heartbeat loop (I-LSM7)
# ---------------------------------------------------------------------------
@final
class BpfLsmSupervisor:
    """rawos-side supervisor driving the holder-daemon heartbeat (I-LSM7).

    When enabled=True (post-24B.1), the supervisor sends periodic heartbeats
    to the holder. If rawos wedges and heartbeats stop, the holder self-detaches
    after `heartbeat_interval_s * holder_timeout_multiplier` seconds (configured
    on the holder side), preventing a wedged rawos from holding the machine
    hostage.

    When enabled=False (24B.0 dormant), run() returns immediately without
    sending any heartbeat — the client is a _NullHolderClient anyway.
    """

    def __init__(
        self,
        client: BpfLsmHolderClient,
        heartbeat_interval_s: float,
        enabled: bool,
    ) -> None:
        self._client = client
        self._heartbeat_interval_s = heartbeat_interval_s
        self._enabled = enabled

    async def run(self) -> None:
        """Main loop. Returns immediately when disabled (I-LSM12 dormant)."""
        if not self._enabled:
            return

        while True:
            try:
                await self._client.heartbeat()
            except Exception:
                # Heartbeat failure logged but does not crash supervisor; the
                # holder's own deadman timer handles silence (I-LSM7). A future
                # phase may add structured logging here.
                pass
            await asyncio.sleep(self._heartbeat_interval_s)
