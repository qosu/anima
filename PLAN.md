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

### Pass 1 — CLOSED (2026-06-09)

All five items answered from direct evidence (git hooks, systemd units, test imports, tools.py dispatch, scheduler loop registration). No assumptions.

1. **Auto-deploy/auto-restart-on-push hook**: NONE. `.git/hooks/` contains only `.sample` files. No CI configs anywhere in the tree. The only systemd units touching `/root/rawos` are `rawos.service` (`Restart=always`, no path/exec triggers tied to git state) and `rawos-reset-budgets.timer` (daily oneshot, `scripts/reset_daily_budgets.py`, contains zero git/subprocess/restart calls — pure DB budget reset). `rawos-web.service` runs in a separate directory (`/root/rawos-web`), out of scope. **CONFIRMED CLEAN.**

2. **TIER 1 test coverage**: **ZERO.** `grep -rl 'evaluation|dataset|study\.|timing\.|manifester' tests/*.py` returns nothing — none of the 12 files in `tests/` (test_api, test_billing_stripe, test_models, test_phase2-5, plus conftest/locust/load-test scaffolding) reference `evaluation/`, `dataset/`, `study/`, `timing/`, or `manifester/` at all. **DECISION**: TIER 1 self-modification cannot start with "edit source, run suite, verify" — the suite is structurally blind to TIER 1 modules; a regression there is undetectable. Phase 16 Pass 2 implementation MUST start TIER 1 in **bootstrap mode**: the agent's first N self-modification cycles for any TIER 1 module are restricted to **adding new test files only** (zero edits to existing `.py` source in that module), until that module has dedicated coverage. Only after a TIER 1 module has its own passing tests does source-editing unlock for that specific module. This is enforced per-module, not globally — a module gaining tests doesn't unlock its siblings.

3. **`write_file` / enforcement chokepoint**: `rawos/kernel/tools.py:690`, `async def execute(tool_name, params, workdir)` — single dispatch point for ALL tools (`write_file`, `bash`, `bash_readonly`, `read_file`, `list_files`, `fetch_url`, `deploy`, `git_branch`, `git_commit`) via `REGISTRY.get(tool_name)`. `_write_file` (line 210) only calls `validate_path()` (traversal check), no TIER awareness. `_deploy` (line 343) is inert w.r.t. `/root/rawos` — generates a `https://downgrade.app/preview/...` URL string only, no filesystem/git side effects. **DECISION**: TIER enforcement wraps `execute()` itself, not individual tool impls — see Pass 2 design below.

4. **Self-probe cadence/scheduling**: Existing loops (all started via `asyncio.create_task` in `rawos/api/app.py` `lifespan`/startup, lines 58-63): `db_sync_loop` (30s), `proactive_scan_loop` (`SCAN_INTERVAL_S=120s`), `_personal_watcher_reload_loop`, `_daily_snapshot_loop` (study, daily), `_calendar_sync_loop_task`, `autonomous_server_scan_loop` (`AUTONOMOUS_SCAN_INTERVAL_S=600s`). **DECISION**: new `rawos_self_probe_loop()`, registered as a 7th `asyncio.create_task(..., name="rawos-self-probe")` in the same startup block, `SELF_PROBE_INTERVAL_S = 21600` (6h) — distinctly separate cadence from the 30s/120s/600s/daily tiers, matching "rare, reviewable cycles" intent (no auto-restart/auto-merge for at minimum the first N cycles, per the existing Process section).

5. **bash/shell bypass risk**: CONFIRMED REAL (carried over from the pre-Phase-16 remediation finding). `_bash` (tools.py:72) runs unrestricted shell via `run_bash()` (sandbox.py) with only resource-limit (`ulimit`) constraints — no path allowlist. A TIER-1-only `write_file` gate alone is meaningless; `_bash` with `sed -i`/`cat >`/`python3 -c "open(...).write(...)"` reaches any path. **DECISION**: same `execute()`-level wrapper from item 3 covers this — see Pass 2 design.

**Pass 1 verdict**: all 5 items answered with evidence, zero open questions remain. Pass 2 may begin.

---

### Pass 2 — implementation design (APPROVED FOR IMPLEMENTATION, not yet written)

**Single enforcement mechanism — git-diff detect-and-revert wrapper around `execute()`** (`rawos/kernel/tools.py:690`):

```
async def execute(tool_name, params, workdir):
    repo_root = await _resolve_repo_root(workdir)   # git rev-parse --show-toplevel, or None
    is_self = (repo_root == "/root/rawos")

    if is_self and tool_name in MUTATING_TOOLS:      # write_file, bash, git_commit, git_branch
        before = _git_status_porcelain(repo_root)     # snapshot

    result = await REGISTRY[tool_name](params, workdir)

    if is_self and tool_name in MUTATING_TOOLS:
        after = _git_status_porcelain(repo_root)
        changed = _diff_paths(before, after)
        violations = [p for p in changed if not _in_tier1_allowlist(p, params)]
        if violations:
            for p in violations:
                _git_checkout_restore(repo_root, p)    # revert exactly the violating paths
            result = ToolResult(
                output=result.output + f"\n\nTIER VIOLATION: reverted {violations} "
                       f"(outside TIER 1 allowlist for /root/rawos self-modification)",
                success=False, duration_ms=result.duration_ms,
            )
    return result
```

Properties:
- Tool-agnostic: catches `write_file`, `bash` (`sed -i`, heredocs, `python3 -c`), `git_commit` (which would otherwise commit the violating files) — closes item 5 without a separate `_bash` guard.
- Allowlist (`_in_tier1_allowlist`) starts as: `tests/**` (new files only, per item 2 bootstrap rule), `evaluation/**`, `dataset/**`, `study/**`, `timing/**`, `manifester/**`, `docs/**` — and for the bootstrap period, a TIER 1 module's existing `.py` files are allowlisted for write ONLY IF a corresponding `tests/test_<module>_*.py` already exists and passes.
- `_targets_rawos_own_repo` (already shipped in `1d805342`) becomes `_resolve_repo_root() == "/root/rawos"` — reuse, don't duplicate.
- Self-probe loop (item 4): `rawos_self_probe_loop()`, 6h interval, operates on a `git worktree add /root/rawos-self-probe-worktree <branch>` — NEVER directly on `/root/rawos`'s working tree, eliminating the HEAD-churn class of bug entirely for self-probes (CONTRIBUTE commits land on `rawos/self-improve-*` branches inside the worktree, then are visible to `/root/rawos`'s `.git` via shared object store — human reviews/merges/cherry-picks from there).
- NO auto-restart, NO auto-merge — unchanged from existing Process step 6.

**Not yet implemented** — this is the design to be coded in the next session's Pass 2, starting with: (a) `_resolve_repo_root`/`_git_status_porcelain`/`_diff_paths`/`_git_checkout_restore`/`_in_tier1_allowlist` helpers in `tools.py`, (b) the `execute()` wrapper, (c) `MUTATING_TOOLS` constant, (d) unit tests for the wrapper itself (TIER 0 violation reverted, TIER 1 bootstrap-mode write allowed/blocked correctly, non-self-repo workdir unaffected), (e) the worktree-based self-probe loop + registration in `app.py`. Each sub-step gets its own commit + full 161-test run before proceeding to the next.


### Pre-Phase-16 hazard remediation — DONE (2026-06-09)

Pass 1 diagnosis surfaced an active production hazard unrelated to but blocking Phase 16: `/root/rawos`'s own working tree (== `rawos.service` `WorkingDirectory`, `Restart=always`) was being repeatedly `git checkout -b`'d by the live scheduler, because SERVER_SCAN/NEEDS_ATTENTION triggers bypass `_select_entity_probe_target` via `workdir_override=anomaly.affected_path` and `_git_branch`/`_git_commit` had no repo-root awareness. Resolved:

- **A** `2fddcb2b` — committed verified Phase 14/15 production fixes (context_reader.py, proactive.py: python3 test runner, -x --tb=line, 90s timeout)
- **B** `769ce9ef` — recovered 425-line uncommitted md_reporter CLI work (--test-results/--discover/--coverage)
- **C** `master` fast-forwarded to `1d805342` (was 7 commits behind, clean ff, no checkout)
- **D** `1d805342` — root-cause fix: new `_targets_rawos_own_repo(workdir)` helper in `rawos/kernel/tools.py`, checked at top of `_git_branch` and `_git_commit`; either returns `error: refusing to ... — SIGNAL instead` if `git rev-parse --show-toplevel == /root/rawos`. Verified: `ast.parse` OK, full suite 161 passed, service restart confirmed healthy (port 8002 listening, /metrics 200).

This also answers Pass 1 checklist item 5 partially: the bash/shell tool (`run_bash`, sandbox.py) has no repo-root guard yet — `_targets_rawos_own_repo` only covers the `_git_branch`/`_git_commit` tool calls. A `sed -i`/`cat >` via `run_bash` against `/root/rawos` source files is still possible. This remains open for Pass 2's TIER enforcement design (must be git-diff-based detect-and-revert after every tool round, not just write_file allowlist, and self-probe must run in an isolated `git worktree`, never `/root/rawos` directly).
