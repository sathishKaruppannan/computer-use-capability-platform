"""Deterministic LLMProvider for tests -- no network call, no API key. See llm/provider.py."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class MockLLMProvider:
    """Wraps either a static dict (always returned) or a responder callable, so a test can script
    exactly what "the model decided" without any real provider involved."""

    name = "mock:v1"

    def __init__(
        self,
        response: dict[str, Any] | Callable[[str, str, dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._response = response

    async def complete_json(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        if callable(self._response):
            return self._response(system_prompt, user_prompt, json_schema)
        return dict(self._response)
