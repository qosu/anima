"""tests/test_self_narrative.py — TDD for the LLM-authored self-narrative writer.

Mocks ONLY the LLM boundary (anima.kernel.summarizer._complete) — everything
else (DB persistence, prompt assembly) runs against real code.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch


def test_write_self_narrative_calls_llm_with_prior_and_context():
    from anima.kernel.self_narrative import write_self_narrative

    with patch("anima.kernel.self_narrative._complete", new=AsyncMock(return_value="I am anima, still mid checkout flow.")) as mock_complete:
        result = asyncio.run(write_self_narrative(
            prior_narrative="I am anima, just starting the checkout flow.",
            user_model={"inferred_goal": "Ship the checkout flow", "active_domains": ["feature"]},
            episodic_history=[{"action_summary": "wrote checkout.py", "outcome": "success"}],
        ))

    assert result == "I am anima, still mid checkout flow."
    mock_complete.assert_called_once()
    _, call_kwargs = mock_complete.call_args
    call_args = mock_complete.call_args.args
    full_text = " ".join(str(a) for a in call_args) + " ".join(str(v) for v in call_kwargs.values())
    assert "Ship the checkout flow" in full_text
    assert "I am anima, just starting the checkout flow." in full_text
    assert "wrote checkout.py" in full_text


def test_write_self_narrative_returns_prior_when_llm_returns_empty():
    from anima.kernel.self_narrative import write_self_narrative

    with patch("anima.kernel.self_narrative._complete", new=AsyncMock(return_value="")):
        result = asyncio.run(write_self_narrative(
            prior_narrative="I am anima, just starting the checkout flow.",
            user_model={"inferred_goal": "Ship the checkout flow"},
            episodic_history=[],
        ))

    assert result == "I am anima, just starting the checkout flow."


def test_write_self_narrative_returns_empty_when_no_prior_and_llm_empty():
    from anima.kernel.self_narrative import write_self_narrative

    with patch("anima.kernel.self_narrative._complete", new=AsyncMock(return_value="")):
        result = asyncio.run(write_self_narrative(
            prior_narrative=None,
            user_model={"inferred_goal": "Ship the checkout flow"},
            episodic_history=[],
        ))

    assert result == ""
