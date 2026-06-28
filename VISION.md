# Vision

## The question rawos is trying to answer

When an AI system runs on a computer, who owns the computer?

Today the answer is always "the infrastructure team" or "the OS" or "the cloud provider." The AI is a tenant. It runs inside whatever the substrate allows. Its actions are constrained by policies it did not author and cannot inspect. If it needs to do something the OS does not permit, it fails silently or crashes. If it does something harmful, the substrate does not stop it — the application layer does, imperfectly, in software.

rawos is an attempt to answer that question differently: the AI owns the computer.

Not in a metaphorical sense. Literally: the AI entity is the policy author for BPF LSM rules that govern what processes can do on the host. It authors systemd units. It manages Landlock namespaces that restrict its own bash subprocesses. It holds the key that signs its own audit log. It decides when to flip enforcement from audit to deny. It manages its own update cycle.

This is not a chatbot that also has some admin tools. It is an entity for which the Linux host is substrate — the way a body is substrate for a mind.

## Why this matters

There are two ways to make autonomous AI systems safer on real infrastructure.

The first is to contain them: walls, sandboxes, capability lists, rate limits, human approval for every interesting action. This works until the containment strategy meets the actual complexity of what you need the AI to do. At that point you either degrade the AI's usefulness or you widen the holes in the walls.

The second is to make the AI itself a good actor at the infrastructure layer: one that has internalized why certain actions are irreversible, why cross-tenant access is wrong, why capability escalation by untrusted reasoning is dangerous — and that enforces these things through the kernel, not through convention.

rawos pursues the second path. The safety floors are not guards around the AI. They are invariants the AI holds about itself.

## The safety doctrine

The hardest design decision in rawos is this: **zero-lockout beats tamper-resistance.**

Any system where the AI can produce a state from which the substrate cannot be recovered is a system that will eventually brick itself. This is a stronger constraint than "log everything" or "require human approval." It means: no matter what the AI does — through bug, through malicious reasoning, through a kernel exploit it did not anticipate — the substrate can come back.

This requires that enforcement mechanisms be designed to fail open for recovery, not closed. Deadman timers revert policy. BPF LSM starts in audit mode. Every irreversible action has a declared undo path before it executes, or it does not execute.

The tradeoff: a sufficiently determined root-on-host attacker can disable these recovery paths. We accept this. The alternative — a system that can prevent root-level recovery — is a system that can also permanently brick itself. The audit chain mirrored off-box catches the attacker; it does not stop them.

## What we are building toward

The current implementation realizes the thesis on a single Linux host:

- The AI entity manages its own systemd units and observes the boot topology of the machine it inhabits.
- BPF LSM enforcement is live in audit mode, with a human-gated flip to enforce.
- Landlock restricts the AI's own subprocesses at the kernel level.
- The reversibility floor and deadman are active in production.
- The audit chain is hash-chained, ECDSA-signed, and mirrored off-box.

The directions we are not yet satisfied with:

**Multi-host substrate.** rawos currently owns one machine. An AI entity that can own a cluster — maintaining coherent policy across machines, with distributed audit chain and cross-node deadman — is a harder problem and a more useful one.

**Verified boot integrity.** Kernel measured boot (TPM + dm-verity) would make the substrate tamper-resistant preventively, not just detectably. This requires hardware support we have not yet confirmed on our deployment target.

**Formal capability model.** The capability gate is currently a software invariant enforced by convention and tests. A formally verified capability lattice — where capability escalation is provably impossible through untrusted reasoning — is the correct long-term architecture for I-SEC6.

**Self-authoring substrate.** The AI currently manages its substrate through authored systemd units and BPF programs. An AI that can author new kernel modules — with the same dormant→audit→enforce lifecycle — would close the gap between "AI manages OS" and "AI is OS."

## What this is not

rawos is not a general-purpose AI agent framework. It does not abstract away the substrate. The point is that the substrate is visible and owned by the entity that runs on it.

It is not a security product for AI systems you distrust. The safety floors assume an AI entity that wants to be safe and is trying to reason correctly about safety. They are not designed to contain a malicious AI.

It is not finished. The vision is not "we have solved AI safety on Linux." The vision is "we are building toward an entity whose relationship with its substrate is honest, explicit, and under shared governance between the AI and the humans who own the machine."
