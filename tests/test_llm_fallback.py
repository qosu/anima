"""Tests for LLM 429 fallback behavior in rawos.kernel.llm_client."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from anima.kernel import llm_client


def _mock_async_client(resp):
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _resp(status: int, body: dict | None = None, text: str = ""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    if body is not None:
        r.json.return_value = body
    return r


class TestCompleteFallback:
    @pytest.mark.asyncio
    async def test_falls_back_on_429(self, monkeypatch):
        monkeypatch.setattr(llm_client.settings, "llm_api_key", "k")
        monkeypatch.setattr(llm_client.settings, "llm_base_url", "https://x.com/v1")
        monkeypatch.setattr(llm_client.settings, "llm_timeout_s", 30)
        monkeypatch.setattr(llm_client.settings, "llm_fallback_model", "fallback-model")

        resp_ok = _resp(200, {"choices": [{"message": {"content": "pong"}}], "usage": {}})
        # first AsyncClient → 429; second AsyncClient (fallback) → 200
        with patch("httpx.AsyncClient", side_effect=[
            _mock_async_client(_resp(429)),
            _mock_async_client(resp_ok),
        ]):
            content, _ = await llm_client.complete(
                [{"role": "user", "content": "hi"}],
                model="primary-model",
                max_tokens=10,
            )
        assert content == "pong"

    @pytest.mark.asyncio
    async def test_raises_clean_error_when_no_fallback(self, monkeypatch):
        monkeypatch.setattr(llm_client.settings, "llm_api_key", "k")
        monkeypatch.setattr(llm_client.settings, "llm_base_url", "https://x.com/v1")
        monkeypatch.setattr(llm_client.settings, "llm_timeout_s", 30)
        monkeypatch.setattr(llm_client.settings, "llm_fallback_model", "")

        with patch("httpx.AsyncClient", return_value=_mock_async_client(_resp(429))):
            with pytest.raises(RuntimeError, match="unavailable"):
                await llm_client.complete(
                    [{"role": "user", "content": "hi"}],
                    model="primary-model",
                    max_tokens=10,
                )

    @pytest.mark.asyncio
    async def test_no_infinite_recursion_when_fallback_also_429(self, monkeypatch):
        monkeypatch.setattr(llm_client.settings, "llm_api_key", "k")
        monkeypatch.setattr(llm_client.settings, "llm_base_url", "https://x.com/v1")
        monkeypatch.setattr(llm_client.settings, "llm_timeout_s", 30)
        monkeypatch.setattr(llm_client.settings, "llm_fallback_model", "fallback-model")

        with patch("httpx.AsyncClient", side_effect=[
            _mock_async_client(_resp(429)),  # primary → 429
            _mock_async_client(_resp(429)),  # fallback → 429 (no further recursion)
        ]):
            with pytest.raises(RuntimeError, match="unavailable"):
                await llm_client.complete(
                    [{"role": "user", "content": "hi"}],
                    model="primary-model",
                    max_tokens=10,
                )


class TestToolCallFallback:
    @pytest.mark.asyncio
    async def test_falls_back_on_429(self, monkeypatch):
        monkeypatch.setattr(llm_client.settings, "llm_api_key", "k")
        monkeypatch.setattr(llm_client.settings, "llm_base_url", "https://x.com/v1")
        monkeypatch.setattr(llm_client.settings, "llm_timeout_s", 30)
        monkeypatch.setattr(llm_client.settings, "llm_fallback_model", "fallback-model")

        msg = {"role": "assistant", "content": "done"}
        resp_ok = _resp(200, {"choices": [{"message": msg}], "usage": {}})
        with patch("httpx.AsyncClient", side_effect=[
            _mock_async_client(_resp(429)),
            _mock_async_client(resp_ok),
        ]):
            result, _ = await llm_client.tool_call(
                [{"role": "user", "content": "go"}],
                tools=[],
                model="primary-model",
            )
        assert result == msg

    @pytest.mark.asyncio
    async def test_raises_clean_error_when_no_fallback(self, monkeypatch):
        monkeypatch.setattr(llm_client.settings, "llm_api_key", "k")
        monkeypatch.setattr(llm_client.settings, "llm_base_url", "https://x.com/v1")
        monkeypatch.setattr(llm_client.settings, "llm_timeout_s", 30)
        monkeypatch.setattr(llm_client.settings, "llm_fallback_model", "")

        with patch("httpx.AsyncClient", return_value=_mock_async_client(_resp(429))):
            with pytest.raises(RuntimeError, match="unavailable"):
                await llm_client.tool_call(
                    [{"role": "user", "content": "go"}],
                    tools=[],
                    model="primary-model",
                )

    @pytest.mark.asyncio
    async def test_no_infinite_recursion_when_fallback_also_429(self, monkeypatch):
        monkeypatch.setattr(llm_client.settings, "llm_api_key", "k")
        monkeypatch.setattr(llm_client.settings, "llm_base_url", "https://x.com/v1")
        monkeypatch.setattr(llm_client.settings, "llm_timeout_s", 30)
        monkeypatch.setattr(llm_client.settings, "llm_fallback_model", "fallback-model")

        with patch("httpx.AsyncClient", side_effect=[
            _mock_async_client(_resp(429)),
            _mock_async_client(_resp(429)),
        ]):
            with pytest.raises(RuntimeError, match="unavailable"):
                await llm_client.tool_call(
                    [{"role": "user", "content": "go"}],
                    tools=[],
                    model="primary-model",
                )


def _mock_stream_client_429():
    resp = MagicMock()
    resp.status_code = 429
    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=resp)
    stream_cm.__aexit__ = AsyncMock(return_value=False)
    client = AsyncMock()
    client.stream = MagicMock(return_value=stream_cm)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _mock_stream_client_200(lines: list[str]):
    async def aiter_lines():
        for line in lines:
            yield line

    resp = MagicMock()
    resp.status_code = 200
    resp.aiter_lines = aiter_lines
    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=resp)
    stream_cm.__aexit__ = AsyncMock(return_value=False)
    client = AsyncMock()
    client.stream = MagicMock(return_value=stream_cm)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestStreamFinalFallback:
    @pytest.mark.asyncio
    async def test_falls_back_on_429(self, monkeypatch):
        monkeypatch.setattr(llm_client.settings, "llm_api_key", "k")
        monkeypatch.setattr(llm_client.settings, "llm_base_url", "https://x.com/v1")
        monkeypatch.setattr(llm_client.settings, "llm_timeout_s", 30)
        monkeypatch.setattr(llm_client.settings, "llm_fallback_model", "fallback-model")

        lines = [
            "data: " + json.dumps({"choices": [{"delta": {"content": "ok"}}]}),
            "data: [DONE]",
        ]
        with patch("httpx.AsyncClient", side_effect=[
            _mock_stream_client_429(),
            _mock_stream_client_200(lines),
        ]):
            chunks = [
                c async for c in llm_client.stream_final(
                    [{"role": "user", "content": "hi"}],
                    model="primary-model",
                )
            ]
        assert chunks == ["ok"]

    @pytest.mark.asyncio
    async def test_raises_clean_error_when_no_fallback(self, monkeypatch):
        monkeypatch.setattr(llm_client.settings, "llm_api_key", "k")
        monkeypatch.setattr(llm_client.settings, "llm_base_url", "https://x.com/v1")
        monkeypatch.setattr(llm_client.settings, "llm_timeout_s", 30)
        monkeypatch.setattr(llm_client.settings, "llm_fallback_model", "")

        with patch("httpx.AsyncClient", return_value=_mock_stream_client_429()):
            with pytest.raises(RuntimeError, match="unavailable"):
                async for _ in llm_client.stream_final(
                    [{"role": "user", "content": "hi"}],
                    model="primary-model",
                ):
                    pass
