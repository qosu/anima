"""
Intent route — the core of rawos.
POST /intent  →  SSE stream of AI response tokens.
Loads project memory, streams DeepSeek response, persists exchange.
"""
from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import rawos.db as db
from rawos.ai_engine import AIError, stream_response
from rawos.api.deps import current_user
from rawos.models import (
    Agent, AgentStatus, Event, EventType,
    Intent, IntentStatus, Memory, MemoryTier, MessageRole, User,
)

log = logging.getLogger("rawos.intent")
router = APIRouter()


class IntentRequest(BaseModel):
    project_id: str
    message:    str
    model:      str | None = None


def _build_messages(project_id: str, user_id: str, new_message: str) -> list[dict]:
    """Load episodic memory for project and append new user message."""
    memories = db.get_project_memories(user_id, project_id, tier="episodic", limit=60)
    messages = []
    for m in memories:
        content = m.content
        if isinstance(content, str):
            messages.append({"role": m.role.value, "content": content})
        else:
            messages.append({"role": m.role.value, "content": content})
    messages.append({"role": "user", "content": new_message})
    return messages


async def _intent_sse(
    user: User,
    project_id: str,
    raw_message: str,
    model: str | None,
) -> AsyncIterator[str]:
    # Validate project belongs to user
    project = db.get_project(user.id, project_id)
    if not project:
        yield f"data: {json.dumps({'error': 'project not found'})}\n\n"
        return

    # Create intent record
    intent = Intent(
        user_id=user.id,
        project_id=project_id,
        raw_text=raw_message,
        status=IntentStatus.ROUTING,
    )
    db.create_intent(intent)

    # Create agent for this intent
    agent = Agent(
        user_id=user.id,
        project_id=project_id,
        goal=raw_message[:200],
        model=model or "deepseek-chat",
    )
    agent = agent.transition(AgentStatus.ACTIVE)
    db.create_agent(agent)
    db.update_intent(user.id, intent.id, agent_id=agent.id, status=IntentStatus.EXECUTING)

    # Log agent started
    db.log_event(Event(
        user_id=user.id,
        project_id=project_id,
        agent_id=agent.id,
        type=EventType.AGENT_STARTED,
        payload={"intent_id": intent.id},
    ))

    # Save user message to episodic memory
    db.save_memory(Memory(
        user_id=user.id,
        project_id=project_id,
        agent_id=agent.id,
        tier=MemoryTier.EPISODIC,
        role=MessageRole.USER,
        content=raw_message,
    ))

    # Build message history and stream response
    messages = _build_messages(project_id, user.id, raw_message)
    # Remove the user message we just added above (already in messages)
    # Actually _build_messages includes new_message at the end already.
    # But we ALSO saved it to DB above. On next call it'll be in episodic.
    # Here we pass messages directly — includes history + new user msg.

    full_response: list[str] = []
    error_occurred = False

    try:
        async for chunk in stream_response(messages[:-1] + [{"role": "user", "content": raw_message}], model=model):
            full_response.append(chunk)
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"
    except AIError as e:
        log.error("AI engine error: %s", e)
        error_occurred = True
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

    # Persist assistant response
    if full_response:
        assistant_text = "".join(full_response)
        db.save_memory(Memory(
            user_id=user.id,
            project_id=project_id,
            agent_id=agent.id,
            tier=MemoryTier.EPISODIC,
            role=MessageRole.ASSISTANT,
            content=assistant_text,
        ))

    # Finalize
    final_status = IntentStatus.FAILED if error_occurred else IntentStatus.COMPLETED
    db.update_intent(user.id, intent.id, status=final_status)
    db.update_agent_status(user.id, agent.id, AgentStatus.ARCHIVED)

    db.log_event(Event(
        user_id=user.id,
        project_id=project_id,
        agent_id=agent.id,
        type=EventType.TASK_COMPLETED if not error_occurred else EventType.ERROR,
        payload={"intent_id": intent.id, "response_chars": len("".join(full_response))},
    ))

    yield f"data: {json.dumps({'done': True, 'intent_id': intent.id})}\n\n"


# Python requires this import at module level — fix the generator type hint
from typing import AsyncIterator  # noqa: E402


@router.post("")
async def create_intent(body: IntentRequest, user: User = Depends(current_user)):
    try:
        intent_obj = Intent(user_id=user.id, project_id=body.project_id, raw_text=body.message)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StreamingResponse(
        _intent_sse(user, body.project_id, body.message, body.model),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
