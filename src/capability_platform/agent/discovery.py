from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

from anthropic import APIError as AnthropicAPIError
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from capability_platform.agent.prompts.registry import get_prompt_variant
from capability_platform.computer_use.surface import PlaywrightSurface
from capability_platform.models import (
    ActionType,
    ApplicationBinding,
    CapabilityArtifact,
    Checkpoint,
    ErrorCategory,
    ErrorRule,
    Locator,
    OutputSpec,
    ParameterSpec,
    RiskLevel,
    Step,
    Target,
)
from capability_platform.observability.evidence import EvidenceCollector
from capability_platform.policy.engine import PolicyEngine


class ClaudeDiscoveryAgent:
    def __init__(
        self,
        api_key: str,
        model: str,
        policy: PolicyEngine,
        evidence_root: Path,
        max_steps: int = 20,
        headless: bool = False,
        openai_api_key: str | None = None,
        openai_model: str = "gpt-5-mini",
        prompt_variant: str = "production",
    ) -> None:
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.policy = policy
        self.evidence_root = evidence_root
        self.max_steps = max_steps
        self.headless = headless
        self.prompt = get_prompt_variant(prompt_variant)
        # Fallback only: if a single Anthropic call errors mid-discovery, that one decision
        # falls back to OpenAI instead of aborting the whole run. Not a default provider swap —
        # Claude remains primary; this is never used when Anthropic is healthy.
        self.openai_client = AsyncOpenAI(api_key=openai_api_key) if openai_api_key else None
        self.openai_model = openai_model

    async def _decide(
        self,
        goal: str,
        observation: dict[str, Any],
        history: list[dict[str, Any]],
        evidence: EvidenceCollector,
    ) -> dict[str, Any]:
        user_content = json.dumps(
            {"goal": goal, "observation": observation, "actions_so_far": history}
        )
        try:
            response = await self.client.messages.create(  # type: ignore[arg-type]
                model=self.model,
                max_tokens=800,
                system=self.prompt.system_prompt,
                tools=[self.prompt.action_tool],
                tool_choice={"type": "tool", "name": "browser_action"},
                messages=[{"role": "user", "content": user_content}],
            )
            block = next(block for block in response.content if block.type == "tool_use")
            return dict(block.input)
        except AnthropicAPIError as exc:
            if not self.openai_client:
                raise
            self._fallback_used = True
            evidence.event(
                "discovery.provider_fallback",
                reason=str(exc),
                from_provider=f"anthropic:{self.model}",
                to_provider=f"openai:{self.openai_model}",
            )
            return await self._decide_via_openai(user_content)

    async def _decide_via_openai(self, user_content: str) -> dict[str, Any]:
        assert self.openai_client
        response = await self.openai_client.chat.completions.create(
            model=self.openai_model,
            max_completion_tokens=2000,
            reasoning_effort="low",
            messages=[
                {"role": "system", "content": self.prompt.system_prompt},
                {"role": "user", "content": user_content},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": self.prompt.action_tool["name"],
                        "description": self.prompt.action_tool["description"],
                        "parameters": self.prompt.action_tool["input_schema"],
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": self.prompt.action_tool["name"]}},
        )
        tool_call = response.choices[0].message.tool_calls[0]
        return json.loads(tool_call.function.arguments)

    async def discover(
        self, goal: str, target_url: str, member_id: str = "10001"
    ) -> CapabilityArtifact:
        run_id = str(uuid4())
        evidence = EvidenceCollector(self.evidence_root, run_id)
        surface = PlaywrightSurface(self.headless)
        self._fallback_used = False
        steps: list[Step] = []
        history: list[dict[str, Any]] = []
        extracted: dict[str, str] = {}
        success_target = Target(
            primary=Locator(strategy="text", value="Savings Account", exact=False),
            rationale="Business-state heading confirms the accounts screen",
        )
        self.policy.authorize_url(target_url)
        await surface.start(target_url)
        try:
            for index in range(self.max_steps):
                observation = await surface.observe()
                evidence.event("discovery.observed", step=index, observation=observation)
                decision = await self._decide(goal, observation, history, evidence)
                evidence.event("discovery.decided", step=index, decision=decision)
                action = decision["action"]
                if action == "complete":
                    if not extracted:
                        raise RuntimeError("Model declared completion before extracting an output")
                    if not await surface.visible(success_target):
                        raise RuntimeError(
                            "Model declared completion but the success checkpoint "
                            f"({success_target.primary.value!r}) is not visible on the page"
                        )
                    evidence.event(
                        "discovery.checkpoint_verified", target=success_target.primary.value
                    )
                    break
                if action == "escalate":
                    raise RuntimeError(
                        f"Discovery requested human intervention: {decision['reason']}"
                    )
                if action == "wait":
                    assert surface.page
                    await surface.page.wait_for_timeout(750)
                    history.append(decision)
                    continue

                if "strategy" not in decision:
                    raise RuntimeError(
                        f"Model action '{action}' is missing a required 'strategy' locator: "
                        f"{decision!r}"
                    )
                locator = Locator(
                    strategy=decision["strategy"],
                    value=decision.get("value") or decision.get("name", ""),
                    name=decision.get("name"),
                )
                target = Target(
                    primary=locator,
                    rationale="Accessible semantic target selected during successful Claude discovery",
                )
                step_action = ActionType(action)
                value = decision.get("typed_value")
                if value == member_id:
                    value = "{{memberId}}"
                step = Step(
                    id=f"step-{len(steps) + 1}",
                    action=step_action,
                    description=decision["reason"],
                    target=target,
                    value=value,
                    output=decision.get("output"),
                    risk=self._classify_risk(step_action, target),
                )
                self.policy.authorize_step(step)
                if step_action == ActionType.CLICK:
                    await surface.click(target)
                elif step_action == ActionType.TYPE:
                    await surface.type(
                        target, member_id if value == "{{memberId}}" else value or ""
                    )
                elif step_action == ActionType.EXTRACT:
                    output_name = step.output or "result"
                    extracted[output_name] = await surface.extract(target)
                steps.append(step)
                history.append(decision)
                evidence.event("discovery.acted", step_id=step.id, action=action)
            else:
                raise RuntimeError("Discovery exceeded maximum steps")

            artifact = CapabilityArtifact(
                id="lookup-member-savings-balance",
                name="Lookup member savings balance",
                description="Find a member in the legacy demo app and return the savings balance.",
                application=ApplicationBinding(
                    vendor="Interface Demo", product="Legacy Member Servicing", base_url=target_url
                ),
                inputs=[
                    ParameterSpec(
                        name="memberId",
                        type="string",
                        description="Demo member identifier",
                        pattern=r"^\d{5}$",
                    )
                ],
                outputs=[
                    OutputSpec(
                        name=next(iter(extracted)),
                        type="number",
                        description="Current savings balance",
                    )
                ],
                steps=steps,
                success=Checkpoint(kind="visible", target=success_target),
                discovered_by=(
                    f"anthropic:{self.model}+openai:{self.openai_model} (fallback used) "
                    f"prompt={self.prompt.qualified_id}"
                    if self._fallback_used
                    else f"anthropic:{self.model} prompt={self.prompt.qualified_id}"
                ),
                tags=["member", "savings", "balance", "computer-use"],
            )
            self._enrich_errors(artifact)
            artifact_path = self.evidence_root / "runs" / run_id / "artifact.json"
            artifact_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
            evidence.event("discovery.completed", artifact=artifact.qualified_id)
            return artifact
        except Exception:
            if surface.page:
                await evidence.screenshot(await surface.screenshot(), "discovery-failure")
            raise
        finally:
            await surface.close()

    # Deliberately code-side, never model-decided: the model must not be able to talk its way
    # into a lower risk classification for its own step. Keeps policy independent of planning
    # (CLAUDE.md rule 2) even at the point risk is first assigned, not just when it's enforced.
    MUTATING_CLICK_KEYWORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "save", "submit", "update", "delete", "remove", "confirm", "pay",
            "transfer", "send", "approve", "reject", "deactivate", "activate",
        }
    )

    @classmethod
    def _classify_risk(cls, action: ActionType, target: Target | None) -> RiskLevel:
        if action in (ActionType.EXTRACT, ActionType.WAIT, ActionType.NAVIGATE):
            return RiskLevel.READ_ONLY
        if action in (ActionType.TYPE, ActionType.SELECT):
            return RiskLevel.REVERSIBLE  # data entry only; nothing committed yet
        if action == ActionType.CLICK and target:
            label = " ".join(
                part for part in (target.primary.name, target.primary.value) if part
            ).lower()
            if any(keyword in label for keyword in cls.MUTATING_CLICK_KEYWORDS):
                return RiskLevel.RISKY
        return RiskLevel.READ_ONLY

    @staticmethod
    def _enrich_errors(artifact: CapabilityArtifact) -> None:
        # Attach to every step after the first (not just the last) so a "not found" state is
        # caught as a business outcome as soon as it appears, rather than only after the flow
        # has already tried later steps (e.g. clicking a button that a not-found page lacks).
        if len(artifact.steps) < 2:
            return
        for step in artifact.steps[1:]:
            step.errors.append(
                ErrorRule(
                    code="MEMBER_NOT_FOUND",
                    category=ErrorCategory.BUSINESS,
                    when=Checkpoint(
                        kind="visible",
                        target=Target(
                            primary=Locator(
                                strategy="text", value="Member not found", exact=False
                            ),
                            rationale="Explicit application business outcome",
                        ),
                    ),
                    message="No member exists for the supplied identifier",
                )
            )
