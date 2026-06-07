"""
rawos AI Engine — DeepSeek-only, streaming, context-aware.
Phase 0: conversation only (no tool execution).
Phase 2 will add tool loop on top of this foundation.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx

from rawos.config import settings

log = logging.getLogger("rawos.ai")

_SYSTEM_PROMPT = """\
You are rawos — an AI operating system. You help users accomplish any task \
through conversation. You are direct, capable, and effective. \
When you need more information to complete a task, ask one clear question.\
"""


class AIError(Exception):
    pass


async def stream_response(
    messages: list[dict],
    model: str | None = None,
) -> AsyncIterator[str]:
    """
    Stream assistant response tokens from DeepSeek.
    Yields text chunks. Raises AIError on API failure.
    """
    if not settings.deepseek_key:
        raise AIError("DEEPSEEK_KEY not configured")

    model = model or settings.deepseek_model_pro

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": _SYSTEM_PROMPT}] + messages,
        "stream": True,
        "max_tokens": 4096,
    }

    headers = {
        "Authorization": f"Bearer {settings.deepseek_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream(
                "POST",
                f"{settings.deepseek_base_url}/chat/completions",
                json=payload,
                headers=headers,
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise AIError(f"DeepSeek API {resp.status_code}: {body[:200]}")

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"]
                        text = delta.get("content") or ""
                        if text:
                            yield text
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

        except httpx.TimeoutException:
            raise AIError("DeepSeek API request timed out")
        except httpx.RequestError as e:
            raise AIError(f"DeepSeek API connection error: {e}")


async def complete(
    messages: list[dict],
    model: str | None = None,
) -> tuple[str, int]:
    """
    Non-streaming completion. Returns (full_text, estimated_tokens).
    Used for summaries, internal processing.
    """
    full = []
    async for chunk in stream_response(messages, model=model):
        full.append(chunk)
    text = "".join(full)
    # rough token estimate: ~4 chars/token
    tokens = sum(len(str(m.get("content", ""))) for m in messages) // 4 + len(text) // 4
    return text, tokens
