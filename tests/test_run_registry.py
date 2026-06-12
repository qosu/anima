"""
tests/test_run_registry.py — Stage F: in-process run registry.

The run registry decouples agent-orchestration lifecycle from the SSE
connection that requested it. A background task appends events to a
``Run``; subscribers (the original POST connection, or a later GET
reconnect) replay buffered events and then block for new ones.

All tests are network-free and run the registry directly with asyncio.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from rawos.api.run_registry import RunRegistry, format_sse


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _drain(agen, limit: int | None = None) -> list[str]:
    """Collect frames from an async generator, stopping after `limit` frames
    if given (to avoid hanging on generators that block forever)."""
    out = []
    async for frame in agen:
        out.append(frame)
        if limit is not None and len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# append
# ---------------------------------------------------------------------------

class TestAppend:
    def test_append_assigns_monotonic_seq(self):
        async def _run():
            registry = RunRegistry()
            run = registry.create("run1", "user1")
            seq1 = await registry.append(run, {"type": "chunk", "text": "a"})
            seq2 = await registry.append(run, {"type": "chunk", "text": "b"})
            seq3 = await registry.append(run, {"type": "chunk", "text": "c"})
            assert (seq1, seq2, seq3) == (1, 2, 3)
            assert [e for _, e in run.events] == [
                {"type": "chunk", "text": "a"},
                {"type": "chunk", "text": "b"},
                {"type": "chunk", "text": "c"},
            ]
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# subscribe — replay of a finished run
# ---------------------------------------------------------------------------

class TestSubscribeFinishedRun:
    def test_replays_all_buffered_events_then_stops(self):
        async def _run():
            registry = RunRegistry()
            run = registry.create("run1", "user1")
            await registry.append(run, {"type": "chunk", "text": "a"})
            await registry.append(run, {"type": "chunk", "text": "b"})
            await registry.finish(run, "completed")

            frames = await _drain(registry.subscribe(run, after_seq=0))
            # 2 chunks + terminal run_complete
            assert len(frames) == 3
            assert "chunk" in frames[0]
            assert "chunk" in frames[1]
            assert "run_complete" in frames[2]
        asyncio.run(_run())

    def test_after_seq_filters_already_seen_events(self):
        async def _run():
            registry = RunRegistry()
            run = registry.create("run1", "user1")
            await registry.append(run, {"type": "chunk", "text": "a"})  # seq 1
            await registry.append(run, {"type": "chunk", "text": "b"})  # seq 2
            await registry.finish(run, "completed")                     # seq 3

            # Reconnect after seq 1 — should only see seq 2 (chunk "b") + run_complete
            frames = await _drain(registry.subscribe(run, after_seq=1))
            assert len(frames) == 2
            assert "\"text\": \"b\"" in frames[0]
            assert "run_complete" in frames[1]
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# subscribe — live run (blocks then receives)
# ---------------------------------------------------------------------------

class TestSubscribeLiveRun:
    def test_blocks_then_receives_new_event(self):
        async def _run():
            registry = RunRegistry(keepalive_seconds=5.0)
            run = registry.create("run1", "user1")

            async def _producer():
                await asyncio.sleep(0.05)
                await registry.append(run, {"type": "chunk", "text": "late"})

            task = asyncio.create_task(_producer())
            frames = await _drain(registry.subscribe(run, after_seq=0), limit=1)
            await task
            assert len(frames) == 1
            assert "late" in frames[0]
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# subscribe — keepalive on idle
# ---------------------------------------------------------------------------

class TestSubscribeKeepalive:
    def test_emits_keepalive_comment_when_idle(self):
        async def _run():
            registry = RunRegistry(keepalive_seconds=0.05)
            run = registry.create("run1", "user1")

            frames = await _drain(registry.subscribe(run, after_seq=0), limit=1)
            assert frames == [": keepalive\n\n"]
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# finish
# ---------------------------------------------------------------------------

class TestFinish:
    def test_finish_marks_done_and_appends_run_complete(self):
        async def _run():
            registry = RunRegistry()
            run = registry.create("run1", "user1")
            await registry.finish(run, "completed")
            assert run.done is True
            assert run.events[-1][1] == {"type": "run_complete", "status": "completed"}
        asyncio.run(_run())

    def test_finish_releases_blocked_subscriber(self):
        async def _run():
            registry = RunRegistry(keepalive_seconds=5.0)
            run = registry.create("run1", "user1")

            async def _finisher():
                await asyncio.sleep(0.05)
                await registry.finish(run, "completed")

            task = asyncio.create_task(_finisher())
            frames = await _drain(registry.subscribe(run, after_seq=0))
            await task
            assert len(frames) == 1
            assert "run_complete" in frames[0]
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# eviction
# ---------------------------------------------------------------------------

class TestEviction:
    def test_get_returns_none_after_ttl_expired(self):
        async def _run():
            registry = RunRegistry(run_ttl_seconds=0.01)
            run = registry.create("run1", "user1")
            await registry.finish(run, "completed")
            await asyncio.sleep(0.02)
            assert registry.get("run1") is None
        asyncio.run(_run())

    def test_get_returns_run_before_ttl_expired(self):
        async def _run():
            registry = RunRegistry(run_ttl_seconds=100.0)
            run = registry.create("run1", "user1")
            await registry.finish(run, "completed")
            assert registry.get("run1") is run
        asyncio.run(_run())

    def test_unfinished_run_never_evicted(self):
        async def _run():
            registry = RunRegistry(run_ttl_seconds=0.01)
            run = registry.create("run1", "user1")
            await asyncio.sleep(0.02)
            assert registry.get("run1") is run
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# SSE framing
# ---------------------------------------------------------------------------

class TestFormatSse:
    def test_frame_has_id_event_data_lines(self):
        frame = format_sse(7, {"type": "chunk", "text": "hi"})
        assert frame == 'id: 7\nevent: chunk\ndata: {"type": "chunk", "text": "hi"}\n\n'

    def test_frame_data_round_trips_to_original_event(self):
        event = {"type": "agent_status", "agent_id": "a1", "status": "done"}
        frame = format_sse(3, event)
        data_line = [l for l in frame.split("\n") if l.startswith("data: ")][0]
        assert json.loads(data_line[len("data: "):]) == event
