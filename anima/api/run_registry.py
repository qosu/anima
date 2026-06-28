"""anima/api/run_registry.py — Stage F: in-process orchestration run registry.

Decouples agent-orchestration lifecycle from the SSE connection that
requested it. A background task (`_run_orchestration`) appends events to a
`Run` via `RunRegistry.append`; subscribers (the original POST connection,
or a later GET reconnect) replay buffered events from a given sequence
number and then block for new ones via `RunRegistry.subscribe`.

Single-worker only: this registry is in-process memory, valid because
anima.service runs uvicorn with --workers 1 (see Stage F plan).
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

KEEPALIVE_SECONDS = 15.0
RUN_TTL_SECONDS = 300.0


@dataclass
class Run:
    """A single orchestration run's in-memory event buffer and state."""

    run_id: str
    user_id: str
    events: list[tuple[int, dict]] = field(default_factory=list)
    done: bool = False
    finished_at: float | None = None
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    seq: int = 0


def format_sse(seq: int, event: dict) -> str:
    """Format an event as a native SSE frame with `id:` and `event:` fields."""
    return f"id: {seq}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"


class RunRegistry:
    """In-process registry of in-flight and recently-finished orchestration runs."""

    def __init__(
        self,
        keepalive_seconds: float = KEEPALIVE_SECONDS,
        run_ttl_seconds: float = RUN_TTL_SECONDS,
    ) -> None:
        self._runs: dict[str, Run] = {}
        self.keepalive_seconds = keepalive_seconds
        self.run_ttl_seconds = run_ttl_seconds

    def create(self, run_id: str, user_id: str) -> Run:
        """Register a new run. Evicts expired finished runs first."""
        self._evict_expired()
        run = Run(run_id=run_id, user_id=user_id)
        self._runs[run_id] = run
        return run

    def get(self, run_id: str) -> Run | None:
        """Look up a run by id. Returns None if absent or expired."""
        self._evict_expired()
        return self._runs.get(run_id)

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [
            rid
            for rid, run in self._runs.items()
            if run.done
            and run.finished_at is not None
            and (now - run.finished_at) > self.run_ttl_seconds
        ]
        for rid in expired:
            del self._runs[rid]

    async def append(self, run: Run, event: dict) -> int:
        """Append an event to the run's buffer, assign it a monotonic seq,
        and wake any blocked subscribers. Returns the assigned seq."""
        async with run.cond:
            run.seq += 1
            seq = run.seq
            run.events.append((seq, event))
            run.cond.notify_all()
        return seq

    async def finish(self, run: Run, status: str) -> None:
        """Append the terminal `run_complete` event and mark the run done."""
        await self.append(run, {"type": "run_complete", "status": status})
        async with run.cond:
            run.done = True
            run.finished_at = time.monotonic()
            run.cond.notify_all()

    async def subscribe(self, run: Run, after_seq: int = 0):
        """Yield SSE frames for events with seq > after_seq, in order.

        Blocks for new events on a live run, emitting `: keepalive\\n\\n`
        comment frames if idle longer than `keepalive_seconds`. Stops once
        the run is done and all buffered events have been replayed.
        """
        while True:
            async with run.cond:
                pending = [(s, e) for s, e in run.events if s > after_seq]
                keepalive = False
                if not pending:
                    if run.done:
                        return
                    try:
                        await asyncio.wait_for(
                            run.cond.wait(), timeout=self.keepalive_seconds
                        )
                    except asyncio.TimeoutError:
                        keepalive = True
                    # Re-check pending after waking, still inside lock loop
                    # by falling through to outer while via continue below.

            if pending:
                for seq, event in pending:
                    yield format_sse(seq, event)
                    after_seq = seq
            elif keepalive:
                yield ": keepalive\n\n"
            # else: woke from cond.wait() with new data but pending was
            # computed before waiting — loop back to recompute.


registry = RunRegistry()
