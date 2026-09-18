"""Real OpenAI implementation of LLMProvider. Mirrors the forced-function-call shape already
proven in `agent.discovery.ClaudeDiscoveryAgent._decide_via_openai`.
"""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI


class OpenAIProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.name = f"openai:{model}"

    async def complete_json(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self.client.chat.completions.create(
            model=self.model,
            max_completion_tokens=2000,
            reasoning_effort="low",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "emit_result",
                        "description": "Return the structured result.",
                        "parameters": json_schema,
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "emit_result"}},
        )
        tool_call = response.choices[0].message.tool_calls[0]
        return json.loads(tool_call.function.arguments)
