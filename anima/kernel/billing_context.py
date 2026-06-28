"""ContextVar-based billing attribution for agent_loop._log_usage.

Carries (user_id, intent_id, event_type) through the agent loop call stack
without threading these params through every intermediate function.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_ctx: ContextVar[dict | None] = ContextVar("anima_billing_context", default=None)


@contextmanager
def set_billing_context(user_id: str, intent_id: str | None, event_type: str = "intent"):
    token = _ctx.set({"user_id": user_id, "intent_id": intent_id, "event_type": event_type})
    try:
        yield
    finally:
        _ctx.reset(token)


def get_billing_context() -> dict | None:
    return _ctx.get()
