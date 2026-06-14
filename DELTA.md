CHANGED: rawos/kernel/llm_client.py — 429-specific fallback to llm_fallback_model in complete/tool_call/stream_final
  WHY: mistral-large-3-675b-instruct-2512 persistently 429 (NIM capacity throttle), llm_client had no fallback logic
CHANGED: rawos/config.py — add llm_fallback_model field
CHANGED: .env — LLM_AGENT_MODEL+LLM_SUMMARIZER_MODEL → mistral-medium-3.5-128b (confirmed 200, 431ms TC_YES)
CHANGED: /usr/local/bin/rawos — wrap import in try/except, fallback to shell on any ImportError/SyntaxError
  WHY: 2x lockout caused by SyntaxError in rawos modules propagating to ForceCommand crash
ADDED: tests/test_llm_fallback.py — 8 tests: complete/tool_call/stream_final fallback+no-fallback+no-recursion
  WHY: TDD coverage for new 429 behavior; all 43 related tests green
NEXT: Phase 22 plan (PAM Integration) — needs Opus. Confirm Phase 21 stable first.
