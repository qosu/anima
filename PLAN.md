# rawos — PLAN.md

Last updated: 2026-06-09

---

## What rawos is

rawos is not a coding assistant. It is an autonomous AI entity that inhabits a software ecosystem and acts without being asked.

The thesis: **an AI that acts → self-verifies → self-rates — with no human validation gate.**

Every other AI system in production today is reactive. It waits. It responds. It requires a human to pull the trigger. rawos does not. rawos watches, probes, decides, fixes, verifies, and rates its own work — in a continuous loop — without anyone asking it to.

This is not a product feature. It is a claim about what AI can become.

---

## Completed phases

### Phase 14 — The Accountable Agent (DONE)

**Thesis**: rawos cannot be trusted to CONTRIBUTE if it does not hold itself accountable for outcomes.

**What was built**:
- Decision model: CONTRIBUTE / SIGNAL / SILENCE (first word of agent response, enforced at parse layer)
- CONTRIBUTE protocol: branch → fix → verify (tests or systemctl) → commit with `VERIFIED:` footer; if verify fails → revert → SIGNAL with `REVERTED:` reason
- SIGNAL only for genuinely unfixable: missing credentials, external access, business logic rawos cannot know
- SILENCE as default when nothing concrete to fix — not SIGNAL (false alarm is worse than silence)
- `_parse_verification_result()`: parses VERIFIED:/REVERTED: from agent response synchronously
- `_post_commit_self_rate()`: fallback async self-rating if agent does not self-report
- `MAX_TOOL_ROUNDS` fix: final summarisation call now uses rawos system_prompt, not generic default
- Decision fallback fixed: default is SILENCE, not SIGNAL

**Verified in production**:
- Before Phase 14: STUCK trigger → agent wrote HTML report → defaulted to SIGNAL (wrong)
- After Phase 14: STUCK trigger → SILENCE (correct — nothing concretely fixable)
- No false SIGNALs since deploy

---

### Phase 15 — Intent Grounding via Repo Probe (DONE)

**Thesis**: an agent with a vague goal cannot produce a real fix. rawos must find a concrete target before firing the agent — not infer one from ambient context.

**What was built**:
- `_select_entity_probe_target(user_id)`: picks most recently active watched repo (COMMIT_EDITMSG mtime, last 7d), excludes /root/rawos
- `_probe_repo_for_issues(workdir)`: git log + diff stat + pytest (-x --tb=line -q, 90s timeout, python3 system interpreter) → `{has_failures, commits, diff_stat, test_output}`
- `_detect_and_run_tests(workdir)`: auto-detects pytest.ini / setup.cfg / pyproject.toml
- Agent prompt override when `has_failures=True`: entire context_summary replaced with focused mission block — no ambient noise, no inferred_goal drift
- Probe fires on all triggers except SERVER_SCAN and NEEDS_ATTENTION (which carry specific targets)

**Test runner**: `python3` system interpreter — rawos venv lacks packages (e.g. `openai`) that watched repos import.

**CONTRIBUTE commits made to `sovereign-research-kernel`** (branch: `rawos/fix-test-isolation-and-provider-count`):

| Commit | File | Root cause fixed |
|--------|------|-----------------|
| `ee6b391` | `sovereign/daemon.py` | `_build_components` always used `settings.db_path` for VectorStore — tests with `tmp_path` ledger connected to production `vectorstore.db` held by the running daemon → lock timeout. Fixed: derive path from `ledger.db_path` |
| `ee6b391` | `tests/test_provider_router.py` | `nim_key4` added to config but tests still asserted 3 providers → assertion failure |
| `51ea345` | `sovereign/config.py` | pydantic-settings 2.14 `BaseSettings` defaults to `extra='forbid'`; `MISTRAL_TITLE_KEYS` in `.env` not defined in `Settings` → `ValidationError` at import → all 344 tests failed at collection |

**Result**: 493 passed, 6 warnings, 81.38s. Probe returns `has_failures=False`.

---

## Architecture (stable)

```
STUCK / JUST_FINISHED / ambient (None)
  → _select_entity_probe_target(user_id)
  → _probe_repo_for_issues(workdir)
      has_failures=True  → context_summary = mission block (test failures, no noise)
      has_failures=False → context_summary = ambient (inferred_goal + recent activity)
  → agent loop (MAX_TOOL_ROUNDS=12)
  → decision: CONTRIBUTE / SIGNAL / SILENCE
      CONTRIBUTE → _parse_verification_result() → episodic log

SERVER_SCAN / NEEDS_ATTENTION → bypass probe → agent loop with specific target already in ctx
```

## Security invariants (non-negotiable)

- rawos NEVER commits to main/master directly
- rawos commits only to `rawos/*` branches
- `_DESTRUCTIVE_PATTERNS` blocked: `rm -rf /`, `dd if=`, `systemctl stop rawos`
- `validate_path` in write_file restricted to workdir
- `sandbox_docker=False` in `.env`

### Added for Phase 16 (self-modification) — non-negotiable from this point forward

- When the probe target is `/root/rawos` itself: **default-deny**. rawos may write ONLY to paths in the TIER 1 allowlist (Phase 16 below). Every other path in `/root/rawos` is TIER 0 — read-only, even for rawos.
- TIER 0 is enforced in code at the `write_file` layer (path check against the allowlist), not by prompt instruction alone. A prompt instruction is a request; a path check is a wall.
- rawos NEVER auto-restarts the rawos service.
- rawos NEVER merges its own `rawos/self-improve-*` branches.
- rawos NEVER edits the TIER 0/1/2 definition itself (this section + the code that enforces it) — that boundary can only be changed by a human-authored commit.

---

## Phase 16 — DECIDED (2026-06-09): Self-Modification — rawos maintains rawos

### The decision

Three directions were analysed: full-spectrum probe (depth), consequence loop (accountability), ecosystem expansion (breadth). All three are evolutionary — they make rawos better at a thing rawos already does (find and fix issues in OTHER repos). CI pipelines already do static analysis sweeps; watch-list expansion is a config change; a consequence loop depends on a review signal that does not exist in this ecosystem (no human reviews `rawos/*` branches today).

**Phase 16 = self-modification.** rawos probes its own source tree (`/root/rawos`), identifies real issues within an explicit allowlist, and submits verified patches to itself via `rawos/self-improve-*` branches.

### The claim

> rawos is the first continuously-operating AI entity that reads its own source code, forms its own improvement targets, and submits verified patches to itself — without ever touching its own decision model, security enforcement, or probe-targeting logic.

No production AI system today does this. Copilot does not patch Copilot. Claude Code does not patch Claude Code. The boundary below is what makes this safe enough to attempt: rawos can improve its own *capabilities and coverage* but can never rewrite the *rules that constrain it*.

### Rejected directions (kept for traceability)

| Direction | Why rejected |
|---|---|
| Full-spectrum probe (mypy/ruff/bandit/coverage on watched repos) | Evolutionary — same shape as Phase 15, just more linters. Does not change what rawos *is*. Can be folded into the self-probe (below) instead, applied first to rawos's own code. |
| Consequence loop (track fate of `rawos/*` branches) | No review process exists on this server for those branches. An open branch after 7 days carries no signal — "rejected" and "unseen" are indistinguishable. Revisit only if/when a review workflow exists. |
| Ecosystem expansion (self-register new watch targets) | Low complexity but low leverage — adds breadth to a system whose depth is still shallow (Phase 15 only checks pytest). Self-modification subsumes this: once rawos can safely improve itself, expanding its own watch-list logic becomes a TIER 1 change it can propose. |

---

### THE HARD BOUNDARY — must exist in code before Pass 2 (implementation) begins

**Default-deny model.** TIER 1 is an explicit allowlist. Anything not on it is TIER 0 (read-only). This is inverted from a denylist deliberately: a denylist fails open if something is forgotten; an allowlist fails closed.

**TIER 0 — read-only, even for rawos** (everything not explicitly listed in TIER 1, including but not limited to):
- `rawos/scheduler/proactive.py` — decision model, probe-firing logic, CONTRIBUTE/SIGNAL/SILENCE parsing
- `rawos/kernel/agent_loop.py` — MAX_TOOL_ROUNDS, verification parsing
- `rawos/kernel/context_reader.py` — probe / test-detection logic (the thing being used to probe itself)
- `rawos/kernel/sandbox.py`, `rawos/auth.py`, `rawos/config.py`, `rawos/middleware/rate_limiter.py` — security enforcement, `_DESTRUCTIVE_PATTERNS`, `validate_path`, `sandbox_docker`
- `rawos/api/**` — production service surface (auth, billing, routes)
- `PLAN.md` — rawos does not rewrite its own constraints document
- this TIER 0/1/2 definition and its enforcement code
- everything outside `/root/rawos` (systemd units, `.env`, deploy scripts, other repos)

**TIER 1 — self-improvable (initial allowlist, additive-only)**:
- `/root/rawos/tests/*.py` — new test files, or new test functions added to existing files (raising coverage; not weakening existing assertions)
- `/root/rawos/rawos/evaluation/*.py`
- `/root/rawos/rawos/dataset/*.py`
- `/root/rawos/rawos/study/*.py`
- `/root/rawos/rawos/timing/*.py`
- `/root/rawos/rawos/manifester/*.py`
- `/root/rawos/docs/**` (if/when this directory exists)

**TIER 2 — never read, never probed, excluded entirely**:
- `.env`, `*.pem`, `*.key`, anything matching `*credential*` or `*secret*`
- systemd unit files, deploy scripts

### Process (Pass 2 implementation outline — not started)

1. **Dedicated self-probe path**, separate from `_select_entity_probe_target`. `/root/rawos` must NOT compete with watched repos for "most recently active" — it is always most active (it's the live codebase). Fixed low-frequency cadence (e.g. once per 6h), independent scheduler entry.
2. Self-probe runs `_probe_repo_for_issues('/root/rawos')` but results are filtered: only findings whose file path matches the TIER 1 allowlist are surfaced to the agent. TIER 0 findings are logged for human visibility but never become agent targets.
3. Agent runs under `_ENTITY_SYSTEM_PROMPT` plus an additional hard constraint in the prompt: "You are modifying your own source. You may write ONLY to TIER 1 paths listed below. If the correct fix requires touching any other path, SIGNAL — do not attempt, do not work around the restriction."
4. `write_file` tool itself enforces the TIER 1 allowlist when `workdir == /root/rawos` — this is the wall, not the prompt. Any write attempt outside TIER 1 is rejected at the tool layer regardless of what the agent decided.
5. CONTRIBUTE → branch `rawos/self-improve-*` → fix → run rawos's own test suite (12 files in `/root/rawos/tests/`) → `VERIFIED:` → commit.
6. NO auto-restart. NO auto-merge. Human reviews, merges, and restarts manually for at minimum the first N cycles — N to be defined once cycle 1 is observed.

### Pass 1 — required before any code is written (next session)

- [ ] Confirm no existing auto-deploy / auto-restart-on-push hook is wired to `/root/rawos` (git hooks, systemd path units, CI)
- [ ] Audit `/root/rawos/tests/` (12 files) — what do they actually cover? If TIER 1 modules (`evaluation/`, `dataset/`, `study/`, `timing/`, `manifester/`) have near-zero test coverage today, "run rawos's own test suite" is a weak verification signal — Pass 1 must decide whether TIER 1 starts even narrower (new tests only, zero source edits) until coverage exists
- [ ] Confirm `write_file` tool's current signature/call sites — where exactly the TIER 1 path-check must be inserted so it cannot be bypassed by a different tool (e.g. shell `cat >`, `sed -i` via bash tool)
- [ ] Decide self-probe cadence and where it's scheduled (new entry point vs. extending existing scheduler)
- [ ] Confirm the bash/shell tool available to the agent — if rawos has unrestricted shell access, a TIER-1-only `write_file` check is meaningless; the same default-deny boundary must apply to shell-based file writes too

**Two-pass discipline applies**: Pass 1 above is diagnosis only — read these files, answer these questions, do NOT write the TIER 1 enforcement code yet. Pass 2 begins only once Pass 1's checklist is fully answered and the enforcement mechanism is confirmed to have no bypass.
