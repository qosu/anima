"""tests/test_bpf_lsm.py — TDD for rawos/kernel/bpf_lsm.py (Phase 24B).

TDD Iron Law: this file must go RED before bpf_lsm.py is written
(ModuleNotFoundError: No module named 'anima.kernel.bpf_lsm').

Phase 24B — eBPF LSM machine-wide MAC. The being adds `bpf` to the active LSM
list via GRUB cmdline + reboot (Fact A, inert alone) then supervises an
unpinned BPF LSM link held by a killable holder daemon (Fact B). Holder
death → kernel auto-detach → enforce reverts instantly, no reboot (I-LSM2).

The floor (sshd, systemd, holder, rawos, self-reload, git) is compiled into
the immutable engine bytecode and checked BEFORE any policy-map lookup (I-LSM5).
Policy maps are the dynamic control plane the being writes at runtime.

Unit tests here exercise PURE PYTHON LOGIC ONLY — no BPF attach, no GRUB edit,
no LSM list modification (requires reboot). Tests requiring a live holder or
the bpf-capable LSM list are deferred to the supervised maintenance window
(gates 24B.1+), never run by CI against prod.
"""
from __future__ import annotations

import dataclasses
import hashlib
import os

import pytest

from anima.kernel import bpf_lsm


# ---------------------------------------------------------------------------
# compose_lsm_cmdline — pure, I-LSM9 GRUB safety
# ---------------------------------------------------------------------------
_ACTIVE_LIST = "lockdown,capability,landlock,yama,apparmor"
_EXPECTED_WITH_BPF = "lockdown,capability,landlock,yama,apparmor,bpf"


def test_compose_lsm_cmdline_appends_bpf():
    assert bpf_lsm.compose_lsm_cmdline(_ACTIVE_LIST) == _EXPECTED_WITH_BPF


def test_compose_lsm_cmdline_preserves_exact_order():
    # Order must be exact; compose must not sort or reorder.
    result = bpf_lsm.compose_lsm_cmdline(_ACTIVE_LIST)
    parts = result.split(",")
    assert parts[:-1] == _ACTIVE_LIST.split(",")
    assert parts[-1] == "bpf"


def test_compose_lsm_cmdline_raises_if_bpf_already_present():
    # Idempotency guard: silently adding bpf twice corrupts the cmdline.
    with pytest.raises(bpf_lsm.BpfLsmError):
        bpf_lsm.compose_lsm_cmdline("lockdown,capability,bpf,apparmor")


def test_compose_lsm_cmdline_does_not_add_integrity():
    # `integrity` is NOT in the observed active set on this box; compose must
    # not add it (would silently activate a currently-inactive module — lén
    # kích hoạt module đang tắt, violates exact-reproduction principle).
    result = bpf_lsm.compose_lsm_cmdline(_ACTIVE_LIST)
    assert "integrity" not in result


def test_compose_lsm_cmdline_rejects_empty_input():
    with pytest.raises((bpf_lsm.BpfLsmError, ValueError)):
        bpf_lsm.compose_lsm_cmdline("")


def test_compose_lsm_cmdline_rejects_whitespace_only():
    with pytest.raises((bpf_lsm.BpfLsmError, ValueError)):
        bpf_lsm.compose_lsm_cmdline("   ")


# ---------------------------------------------------------------------------
# validate_boot_config — fail-fast at boot, I-LSM10
# ---------------------------------------------------------------------------
def test_validate_boot_config_noop_when_disabled(monkeypatch):
    # Must not raise regardless of support state when disabled (I-LSM12).
    monkeypatch.setattr(bpf_lsm, "_support_cache", False)
    bpf_lsm.validate_boot_config(enabled=False, mode="audit")


def test_validate_boot_config_raises_when_enabled_and_unsupported(monkeypatch):
    monkeypatch.setattr(bpf_lsm, "_support_cache", False)
    with pytest.raises(bpf_lsm.BpfLsmUnsupportedError):
        bpf_lsm.validate_boot_config(enabled=True, mode="audit")


def test_validate_boot_config_ok_when_enabled_and_supported(monkeypatch):
    monkeypatch.setattr(bpf_lsm, "_support_cache", True)
    bpf_lsm.validate_boot_config(enabled=True, mode="audit")  # must not raise


def test_validate_boot_config_ok_enforce_when_supported(monkeypatch):
    monkeypatch.setattr(bpf_lsm, "_support_cache", True)
    bpf_lsm.validate_boot_config(enabled=True, mode="enforce")  # must not raise


def test_validate_boot_config_raises_on_invalid_mode(monkeypatch):
    monkeypatch.setattr(bpf_lsm, "_support_cache", True)
    with pytest.raises((bpf_lsm.BpfLsmError, ValueError)):
        bpf_lsm.validate_boot_config(enabled=True, mode="superenforce")


def test_validate_boot_config_disabled_is_noop_regardless_of_support(monkeypatch):
    # Even with unsupported + invalid mode, disabled = no-op (I-LSM12).
    monkeypatch.setattr(bpf_lsm, "_support_cache", False)
    bpf_lsm.validate_boot_config(enabled=False, mode="enforce")


# ---------------------------------------------------------------------------
# supported() detection — I-LSM10 + I-LSM11
# ---------------------------------------------------------------------------
def test_supported_returns_false_when_bpf_absent_in_lsm_file(monkeypatch, tmp_path):
    lsm_file = tmp_path / "lsm"
    lsm_file.write_text("lockdown,capability,landlock,yama,apparmor")
    monkeypatch.setattr(bpf_lsm, "_LSM_ACTIVE_PATH", str(lsm_file))
    monkeypatch.setattr(bpf_lsm, "_support_cache", None)
    assert bpf_lsm.supported() is False


def test_supported_returns_true_when_bpf_present_and_infra_exists(
    monkeypatch, tmp_path
):
    lsm_file = tmp_path / "lsm"
    lsm_file.write_text("lockdown,capability,landlock,yama,apparmor,bpf")
    btf_file = tmp_path / "vmlinux"
    btf_file.write_bytes(b"\x00" * 16)  # non-empty stub
    bpffs_dir = tmp_path / "bpf"
    bpffs_dir.mkdir()
    monkeypatch.setattr(bpf_lsm, "_LSM_ACTIVE_PATH", str(lsm_file))
    monkeypatch.setattr(bpf_lsm, "_BTF_PATH", str(btf_file))
    monkeypatch.setattr(bpf_lsm, "_BPFFS_PATH", str(bpffs_dir))
    monkeypatch.setattr(bpf_lsm, "_support_cache", None)
    assert bpf_lsm.supported() is True


def test_supported_returns_false_when_btf_missing(monkeypatch, tmp_path):
    lsm_file = tmp_path / "lsm"
    lsm_file.write_text("lockdown,capability,landlock,yama,apparmor,bpf")
    bpffs_dir = tmp_path / "bpf"
    bpffs_dir.mkdir()
    # btf_file intentionally NOT created
    monkeypatch.setattr(bpf_lsm, "_LSM_ACTIVE_PATH", str(lsm_file))
    monkeypatch.setattr(bpf_lsm, "_BTF_PATH", str(tmp_path / "nonexistent_vmlinux"))
    monkeypatch.setattr(bpf_lsm, "_BPFFS_PATH", str(bpffs_dir))
    monkeypatch.setattr(bpf_lsm, "_support_cache", None)
    assert bpf_lsm.supported() is False


def test_supported_caches_result(monkeypatch, tmp_path):
    # After first call, _support_cache must not be None (result is cached).
    lsm_file = tmp_path / "lsm"
    lsm_file.write_text("lockdown,capability,landlock,yama,apparmor")
    monkeypatch.setattr(bpf_lsm, "_LSM_ACTIVE_PATH", str(lsm_file))
    monkeypatch.setattr(bpf_lsm, "_support_cache", None)
    bpf_lsm.supported()
    assert bpf_lsm._support_cache is not None


# ---------------------------------------------------------------------------
# Artifact integrity — I-LSM11, fail-closed
# ---------------------------------------------------------------------------
def test_artifact_checksum_match_passes(tmp_path):
    artifact = tmp_path / "engine.o"
    content = b"fake bpf object content for checksum test"
    artifact.write_bytes(content)
    expected_sha256 = hashlib.sha256(content).hexdigest()
    bpf_lsm._verify_artifact(str(artifact), expected_sha256)  # must not raise


def test_artifact_checksum_mismatch_fails_closed(tmp_path):
    artifact = tmp_path / "engine.o"
    artifact.write_bytes(b"real content")
    wrong_sha256 = hashlib.sha256(b"different content").hexdigest()
    with pytest.raises(bpf_lsm.BpfLsmError):
        bpf_lsm._verify_artifact(str(artifact), wrong_sha256)


def test_artifact_missing_file_fails_closed(tmp_path):
    with pytest.raises((bpf_lsm.BpfLsmError, FileNotFoundError, OSError)):
        bpf_lsm._verify_artifact(str(tmp_path / "nonexistent.o"), "abc123")


# ---------------------------------------------------------------------------
# Floor guard — I-LSM5, double-guard at policy build time
# ---------------------------------------------------------------------------
def test_floor_comm_is_frozenset():
    assert isinstance(bpf_lsm.FLOOR_COMM, frozenset)


def test_floor_comm_contains_critical_processes():
    # These must ALL be on the floor — operator shell, PID1, holder, rawos.
    for required in ("sshd", "systemd", "rawos-bpf-lsm-h", "rawos", "git"):
        assert required in bpf_lsm.FLOOR_COMM, (
            f"{required!r} missing from FLOOR_COMM — I-LSM5 violation"
        )


def test_is_protected_true_for_all_floor_members():
    for comm in bpf_lsm.FLOOR_COMM:
        assert bpf_lsm.is_protected(comm) is True, (
            f"is_protected({comm!r}) returned False — floor member must always be protected"
        )


def test_is_protected_false_for_non_floor():
    assert bpf_lsm.is_protected("malicious-backdoor-xyz") is False
    assert bpf_lsm.is_protected("curl") is False


def test_build_policy_rejects_deny_comm_intersecting_floor():
    # I-LSM5 double-guard: build_policy must raise if deny_comm ∩ FLOOR_COMM ≠ ∅.
    with pytest.raises(bpf_lsm.BpfLsmError):
        bpf_lsm.build_policy(
            deny_comm=("sshd",),
            protected_comm=(),
            mode="audit",
        )


def test_build_policy_rejects_systemd_in_deny():
    with pytest.raises(bpf_lsm.BpfLsmError):
        bpf_lsm.build_policy(deny_comm=("systemd",), protected_comm=(), mode="audit")


def test_build_policy_ok_for_non_floor_deny():
    policy = bpf_lsm.build_policy(
        deny_comm=("curl", "wget"),
        protected_comm=(),
        mode="audit",
    )
    assert "curl" in policy.deny_comm
    assert "wget" in policy.deny_comm


def test_build_policy_rejects_invalid_mode():
    with pytest.raises((bpf_lsm.BpfLsmError, ValueError)):
        bpf_lsm.build_policy(deny_comm=(), protected_comm=(), mode="unknown-mode")


def test_policy_is_frozen():
    policy = bpf_lsm.build_policy(deny_comm=(), protected_comm=(), mode="audit")
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.mode = "enforce"  # type: ignore[misc]


def test_policy_has_correct_fields():
    policy = bpf_lsm.build_policy(
        deny_comm=("curl",),
        protected_comm=("myapp",),
        mode="enforce",
    )
    assert policy.deny_comm == ("curl",)
    assert policy.protected_comm == ("myapp",)
    assert policy.mode == "enforce"


# ---------------------------------------------------------------------------
# GRUB custom entry composer — I-LSM9, pure function
# ---------------------------------------------------------------------------
_BASE_CMDLINE = (
    "BOOT_IMAGE=/boot/vmlinuz-6.8.0-117-generic "
    "root=UUID=2ab00f5c-7182-4670-998e-e4f142f71767 ro "
    "consoleblank=0 systemd.show_status=true console=tty1 console=ttyS0"
)
_LSM_CMDLINE = "lsm=lockdown,capability,landlock,yama,apparmor,bpf"
_KERNEL_VER = "6.8.0-117-generic"
# The known-good entry 0 stable id (must NEVER appear in custom entry — I-LSM9).
_ENTRY0_ID = "gnulinux-simple-2ab00f5c-7182-4670-998e-e4f142f71767"


def test_compose_grub_custom_entry_has_id():
    entry = bpf_lsm.compose_grub_custom_entry(_BASE_CMDLINE, _LSM_CMDLINE, _KERNEL_VER)
    assert "--id rawos-bpf-lsm" in entry


def test_compose_grub_custom_entry_has_lsm_cmdline():
    entry = bpf_lsm.compose_grub_custom_entry(_BASE_CMDLINE, _LSM_CMDLINE, _KERNEL_VER)
    assert _LSM_CMDLINE in entry


def test_compose_grub_custom_entry_includes_base_cmdline_args():
    entry = bpf_lsm.compose_grub_custom_entry(_BASE_CMDLINE, _LSM_CMDLINE, _KERNEL_VER)
    # Root UUID must appear on the linux line (not just in the search directive).
    assert "root=UUID=2ab00f5c" in entry


def test_compose_grub_custom_entry_does_not_use_entry0_id():
    # I-LSM9: must not contaminate or reference the known-good entry 0 id.
    entry = bpf_lsm.compose_grub_custom_entry(_BASE_CMDLINE, _LSM_CMDLINE, _KERNEL_VER)
    assert _ENTRY0_ID not in entry


def test_compose_grub_custom_entry_starts_with_menuentry():
    entry = bpf_lsm.compose_grub_custom_entry(_BASE_CMDLINE, _LSM_CMDLINE, _KERNEL_VER)
    assert entry.strip().startswith("menuentry")


def test_compose_grub_custom_entry_has_initrd():
    entry = bpf_lsm.compose_grub_custom_entry(_BASE_CMDLINE, _LSM_CMDLINE, _KERNEL_VER)
    assert f"initrd.img-{_KERNEL_VER}" in entry


def test_compose_grub_custom_entry_raises_on_missing_uuid():
    bad_cmdline = "BOOT_IMAGE=/boot/vmlinuz-6.8.0-117-generic ro"  # no root=UUID
    with pytest.raises(bpf_lsm.BpfLsmError):
        bpf_lsm.compose_grub_custom_entry(bad_cmdline, _LSM_CMDLINE, _KERNEL_VER)


# ---------------------------------------------------------------------------
# BpfLsmSupervisor — rawos-side heartbeat loop (I-LSM7)
# ---------------------------------------------------------------------------
async def test_supervisor_run_is_noop_when_disabled():
    # enabled=False → run() returns immediately without calling heartbeat.
    calls: list[str] = []

    class _TrackingClient(bpf_lsm.BpfLsmHolderClient):
        async def heartbeat(self) -> None:
            calls.append("heartbeat")

        async def flip_mode(self, mode: str) -> None:
            pass

        async def update_policy(self, policy: bpf_lsm.Policy) -> None:
            pass

        async def detach(self) -> None:
            pass

    supervisor = bpf_lsm.BpfLsmSupervisor(
        client=_TrackingClient(),
        heartbeat_interval_s=0.01,
        enabled=False,
    )
    await supervisor.run()
    assert calls == [], f"heartbeat should not be called when disabled, got {calls}"


async def test_null_client_heartbeat_is_noop():
    # _NullHolderClient must not raise (used when dormant).
    client = bpf_lsm._NullHolderClient()
    await client.heartbeat()  # must not raise
    await client.flip_mode("audit")  # must not raise
    await client.detach()  # must not raise


# ---------------------------------------------------------------------------
# _SocketHolderClient — thin unix-socket wrapper (I-LSM7 live path)
# ---------------------------------------------------------------------------
def test_holder_sock_path_constant_exists():
    assert hasattr(bpf_lsm, '_HOLDER_SOCK_PATH')
    assert bpf_lsm._HOLDER_SOCK_PATH.endswith('.sock')


async def test_socket_client_heartbeat_raises_on_no_holder():
    # When holder is not running, _SocketHolderClient must raise (supervisor catches).
    client = bpf_lsm._SocketHolderClient(
        sock_path='/tmp/rawos-bpf-lsm-holder-NONEXISTENT.sock'
    )
    with pytest.raises(Exception):
        await client.heartbeat()


async def test_socket_client_detach_raises_on_no_holder():
    client = bpf_lsm._SocketHolderClient(
        sock_path='/tmp/rawos-bpf-lsm-holder-NONEXISTENT.sock'
    )
    with pytest.raises(Exception):
        await client.detach()



# ---------------------------------------------------------------------------
# 24B.3 -- I-LSM7 supervisor resilience + socket command format (deadman drill)
# ---------------------------------------------------------------------------
async def test_supervisor_continues_after_heartbeat_failure():
    """I-LSM7: supervisor must not crash on heartbeat exception, continues loop.

    Mirrors 24B.3 deadman drill: rawos survived holder death; heartbeats
    failed (ConnectionRefusedError) and were caught silently. rawos stayed up.
    """
    import asyncio
    calls: list[str] = []

    class _FailOnceClient(bpf_lsm.BpfLsmHolderClient):
        async def heartbeat(self) -> None:
            calls.append('heartbeat')
            if len(calls) == 1:
                raise ConnectionRefusedError('holder not running (simulated)')

        async def flip_mode(self, mode: str) -> None:
            pass

        async def update_policy(self, policy: bpf_lsm.Policy) -> None:
            pass

        async def detach(self) -> None:
            pass

    supervisor = bpf_lsm.BpfLsmSupervisor(
        client=_FailOnceClient(),
        heartbeat_interval_s=0.01,
        enabled=True,
    )
    try:
        await asyncio.wait_for(supervisor.run(), timeout=0.1)
    except asyncio.TimeoutError:
        pass

    assert len(calls) >= 2, (
        f'supervisor stopped after first failure (I-LSM7 violated); calls={calls}'
    )


def test_socket_client_flip_mode_sends_correct_command(tmp_path):
    """_SocketHolderClient._send must deliver exact command bytes.

    Verifies the wire format used during 24B.3 enforce flip + revert cycle.
    Checks: 'mode enforce' and 'mode audit' both terminated with newline.
    """
    import socket
    import threading

    NEWLINE = bytes([10])  # avoids backslash-n escape in generated file
    sock_path = str(tmp_path / 'test_holder_flip.sock')
    received: list[bytes] = []
    ready = threading.Event()

    def _server() -> None:
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)
        ready.set()
        for _ in range(2):  # accept 2 connections: enforce + audit
            conn, _ = srv.accept()
            data = b''
            while NEWLINE not in data:
                chunk = conn.recv(64)
                if not chunk:
                    break
                data += chunk
            received.append(data)
            conn.sendall(b'ok' + NEWLINE)
            conn.close()
        srv.close()

    t = threading.Thread(target=_server, daemon=True)
    t.start()
    ready.wait(timeout=2)

    client = bpf_lsm._SocketHolderClient(sock_path=sock_path)
    client._send('mode enforce')
    client._send('mode audit')
    t.join(timeout=2)

    expected = [b'mode enforce' + NEWLINE, b'mode audit' + NEWLINE]
    assert received == expected, f'unexpected wire commands: {received}'
