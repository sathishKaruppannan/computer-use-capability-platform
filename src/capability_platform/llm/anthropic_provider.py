"""Real Anthropic implementation of LLMProvider. Mirrors the forced-tool-call shape already
proven in `agent.discovery.ClaudeDiscoveryAgent._decide` -- a single tool, tool_choice pinned to
it, so the response is always a structured dict, never free text to parse.
"""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic


class AnthropicProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.name = f"anthropic:{model}"

    async def complete_json(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=800,
            system=system_prompt,
            tools=[
                {
                    "name": "emit_result",
                    "description": "Return the structured result.",
                    "input_schema": json_schema,
                }
            ],
            tool_choice={"type": "tool", "name": "emit_result"},
            messages=[{"role": "user", "content": user_prompt}],
        )
        block = next(block for block in response.content if block.type == "tool_use")
        return dict(block.input)
