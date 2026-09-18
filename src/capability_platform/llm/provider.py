"""Provider-independent LLM seam. Mirrors `computer_use.surface.SurfaceAdapter`: callers (e.g.
`agent.intent_analyzer.IntentAnalyzer`) depend only on this Protocol, never on a provider SDK
directly -- so a mock implementation makes them fully deterministic in tests with no network
call and no API key.
"""

from __future__ import annotations

from typing import Any, Protocol


class LLMProvider(Protocol):
    name: str  # provenance tag, e.g. "anthropic:claude-sonnet-4-5", "mock:v1"

    async def complete_json(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Return a dict matching `json_schema`. Implementations force the underlying model to
        emit structured output (a tool call / function call), never free-text parsing."""
        ...
