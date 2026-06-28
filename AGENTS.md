# AGENTS.md — Working with Anima as an AI agent

This file is for AI coding agents (Claude Code, Codex, Copilot, etc.) working
on Anima codebase. It documents the architecture, safety constraints, and
conventions you need to understand before making any change.

## Read this first

Anima is an autonomous AI entity that owns the policy layer of its Linux
substrate. This is not a typical web application. Several kernel modules
(`bpf_lsm.py`, `landlock.py`, `unit_topology.py`) interact with the Linux
kernel directly. Errors in these modules can affect system stability.

**Before editing any kernel module:** read the module header, check which
invariants it enforces (see SECURITY.md), and verify your change preserves all
of them.

## Codebase map

```
rawos/
├── app.py                  # FastAPI application entry point
├── config.py               # Settings (Pydantic); bpf_lsm_mode lives at :178
├── cli/
│   ├── main.py             # Anima CLI entry point
│   └── frontdoor_entry.py  # anima-frontdoor CLI entry point
├── kernel/                 # Core AI entity modules (see below)
├── routers/                # FastAPI routers (auth, billing, agent, admin)
└── tests/                  # Full test suite; run with `make test`
```

### Kernel modules — what each one does

| Module | Role |
|---|---|
| `entity.py` | AI identity, constitution, self-awareness |
| `agent_loop.py` | Cognitive loop: perceive → reason → act → audit |
| `operator.py` | Graduated authorization; capability level management |
| `capability_gate.py` | **Single mediation point** for all privileged actions |
| `reversible_apply.py` | Reversibility floor: every action must have an undo path |
| `frontdoor.py` | Frontdoor floor: minimum safety contract before any action |
| `audit_chain.py` | Append-only, hash-chained, ECDSA-signed audit log |
| `bpf_lsm.py` | BPF LSM machine-wide policy (audit / enforce mode) |
| `landlock.py` | Landlock self-MAC: restricts AI's bash subprocesses |
| `unit_topology.py` | Systemd unit authorship and boot topology management |
| `self_reload.py` | Self-update with hash-verified integrity check |
| `sandbox.py` | Container isolation for untrusted tool execution |
| `tools.py` | Tool execution with SSRF and capability guards |
| `memory_index.py` | Persistent memory, scoped by `(user_id, project_id)` |
| `context_builder.py` | Context assembly with provenance tagging |
| `output_guard.py` | Anti-exfiltration scan before trust boundary crossing |
| `telegram_gate.py` | Off-box notification for critical events |

## Invariants you must not violate

These are enforced by tests and by kernel policy. Violating them is a bug,
not a feature, regardless of the task description:

- Untrusted user code never runs host-direct (`I-SEC2`)
- High-value secrets never present in sandboxed process environment (`I-SEC3`)
- All memory queries scoped to `(user_id, project_id)` — no cross-tenant reads (`I-SEC4`)
- Untrusted content (chat, tool output) structurally separated from trusted content in context (`I-SEC5`)
- All privileged actions pass through `capability_gate.py` — no direct execution (`I-SEC6`)
- `_fetch_url` in `tools.py` default-denies RFC1918, link-local, loopback (`I-SEC8`)
- `make test` output must be pristine after every change (`I-SEC12`)

## How to run tests

```bash
# From repo root, with venv active:
make test

# Or directly:
venv/bin/python -m pytest tests/ --ignore=tests/load_test -q
```

All tests must pass. No new failures permitted.

## TDD requirement

All new code follows RED → GREEN → REFACTOR strictly. Write the failing test
first. Watch it fail. Then write production code. See CONTRIBUTING.md.

## What not to touch without reading invariants first

- `anima/kernel/capability_gate.py` — changes here can silently remove the mediation layer
- `anima/kernel/sandbox.py` — changes here can allow untrusted code to reach the host
- `anima/kernel/context_builder.py` — changes here can collapse provenance separation
- `anima/kernel/audit_chain.py` — changes here can make tampered logs undetectable
- `rawos/config.py:178` (`bpf_lsm_mode`) — this is a machine-wide kernel enforcement toggle

## Commit convention

Subject: imperative, present tense, ≤72 chars.
Body: explain *why*. Include `Co-Authored-By` if AI-assisted.
