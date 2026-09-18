"""Layer 1: natural-language goal -> TaskIntent. Never executes a capability -- pure NL -> typed
dict (via an LLMProvider) -> validated TaskIntent. Depends only on the LLMProvider Protocol, so
tests can be fully deterministic with MockLLMProvider and no network call."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from capability_platform.agent.models import TaskIntent
from capability_platform.agent.prompts.intent_v1 import VARIANT
from capability_platform.llm.provider import LLMProvider
from capability_platform.observability.evidence import EvidenceCollector


class IntentAnalysisError(RuntimeError):
    """Raised when neither provider returns a usable, schema-valid TaskIntent. The orchestrator
    treats this as the final safety net and routes straight to COMPUTER_USE_DISCOVERY."""


class ClarificationRequiredError(RuntimeError):
    """Raised by the orchestrator (not IntentAnalyzer itself -- analyze() always returns a valid
    TaskIntent, ambiguous or not) when TaskIntent.requires_clarification is true. Carries the
    model's own clarification_question so a caller (CLI/REST) can surface it directly instead of
    the pipeline guessing at intent/entities from an unclassifiable goal."""

    def __init__(self, question: str | None) -> None:
        self.question = question or "Please provide more detail about what you'd like to do."
        super().__init__(self.question)


class IntentAnalyzer:
    def __init__(self, provider: LLMProvider, fallback_provider: LLMProvider | None = None) -> None:
        self.provider = provider
        self.fallback_provider = fallback_provider

    async def analyze(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        evidence: EvidenceCollector | None = None,
    ) -> TaskIntent:
        user_prompt = json.dumps({"goal": goal, "context": context or {}})
        raw, provider_name = await self._complete(user_prompt)
        try:
            intent = TaskIntent.model_validate({**raw, "raw_goal": goal, "provider": provider_name})
        except ValidationError as exc:
            raise IntentAnalysisError(f"Provider returned an invalid task intent: {exc}") from exc
        if evidence is not None:
            evidence.event(
                "intent.analyzed", intent=intent.model_dump(mode="json"), provider=provider_name
            )
        return intent

    async def _complete(self, user_prompt: str) -> tuple[dict[str, Any], str]:
        schema = VARIANT.action_tool["input_schema"]
        try:
            raw = await self.provider.complete_json(VARIANT.system_prompt, user_prompt, schema)
            return raw, self.provider.name
        except Exception as exc:
            if not self.fallback_provider:
                raise IntentAnalysisError(f"Intent analysis failed: {exc}") from exc
            try:
                raw = await self.fallback_provider.complete_json(
                    VARIANT.system_prompt, user_prompt, schema
                )
                return raw, self.fallback_provider.name
            except Exception as fallback_exc:
                raise IntentAnalysisError(
                    f"Intent analysis failed on both providers: {fallback_exc}"
                ) from fallback_exc
