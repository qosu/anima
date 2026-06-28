## What and why

<!-- One paragraph: what this PR does and why it is needed. -->

## How it works

<!-- Brief explanation of the approach. Link to relevant modules. -->

## Checklist

- [ ] `make test` passes locally (output pristine — zero failures, zero warnings)
- [ ] All new code written RED → GREEN (failing test first, minimal production code second)
- [ ] No secret, credential, or personal data in diff
- [ ] `.env` not modified (only `.env.example` if adding a new env variable)
- [ ] Security invariants I-SEC1–I-SEC12 preserved
- [ ] If change touches `capability_gate.py`, `sandbox.py`, `context_builder.py`,
      `audit_chain.py`, or `bpf_lsm_mode`: invariant impact explicitly stated below

## Invariant impact (if applicable)

<!-- Which invariants does this change affect, and how are they preserved? -->

## Testing notes

<!-- What did you test beyond `make test`? Any manual verification steps? -->
