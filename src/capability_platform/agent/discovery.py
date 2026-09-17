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
        self,
        goal: str,
        target_url: str,
        member_id: str = "10001",
        extra_known_values: dict[str, str] | None = None,
        system_identifier: str | None = None,
        run_id: str | None = None,
    ) -> CapabilityArtifact:
        run_id = run_id or str(uuid4())
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
        # known_values drives both the compiled-step templating below and what's actually typed
        # into the browser during discovery (memberId is always known; extra_known_values adds
        # e.g. username/password when the target requires a login first).
        known_values: dict[str, str] = {"memberId": member_id, **(extra_known_values or {})}
        effective_goal = goal
        if extra_known_values:
            hint = "; ".join(f"{name}={literal}" for name, literal in extra_known_values.items())
            effective_goal = (
                f"{goal}. If a login/sign-in form appears before reaching the goal, "
                f"authenticate using these credentials: {hint}, then continue toward the goal."
            )
        # A credential literal (never its field name) that leaked into a raw model decision or
        # page observation wouldn't be caught by Redactor's key-name-based patterns (evidence.py)
        # -- so scrub the literal itself wherever discovery logs the model's raw tool-call output
        # or a page snapshot, on top of that existing key-based redaction, not instead of it.
        # "username" is the one known-value name never treated as a secret; everything else
        # extra_known_values carries (password, apiKey, or any future credential name) is --
        # this generalizes past the original password-only scrub without hardcoding each name.
        sensitive_literals = [v for k, v in (extra_known_values or {}).items() if k != "username"]

        def _scrub(value: Any) -> Any:
            if not sensitive_literals:
                return value
            text = json.dumps(value, default=str)
            for literal in sensitive_literals:
                text = text.replace(literal, "[REDACTED]")
            return json.loads(text)

        self.policy.authorize_url(target_url)
        await surface.start(target_url)
        try:
            for index in range(self.max_steps):
                observation = await surface.observe()
                evidence.event("discovery.observed", step=index, observation=_scrub(observation))
                decision = await self._decide(effective_goal, observation, history, evidence)
                evidence.event("discovery.decided", step=index, decision=_scrub(decision))
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
                if value is not None:
                    for placeholder_name, literal in known_values.items():
                        if value == literal:
                            value = f"{{{{{placeholder_name}}}}}"
                            break
                # decision["reason"] is Claude's own free-text explanation of the step -- for a
                # login step it naturally references the literal credential it was told to type
                # (e.g. "Fill in password field with 'hunter2'"), and unlike `value` this text
                # was never templated. It also ends up in the PERSISTED CapabilityArtifact (not
                # just a transient evidence log), so it needs the same literal-substring scrub
                # applied before it's used as the step description, on top of (not instead of)
                # the evidence-trail scrubbing above.
                description = decision["reason"]
                for literal in sensitive_literals:
                    description = description.replace(literal, "[REDACTED]")
                step = Step(
                    id=f"step-{len(steps) + 1}",
                    action=step_action,
                    description=description,
                    target=target,
                    value=value,
                    output=decision.get("output"),
                    risk=self._classify_risk(step_action, target),
                )
                self.policy.authorize_step(step)
                if step_action == ActionType.CLICK:
                    await surface.click(target)
                elif step_action == ActionType.TYPE:
                    await surface.type(target, self._resolve_placeholder(value, known_values))
                elif step_action == ActionType.EXTRACT:
                    output_name = step.output or "result"
                    extracted[output_name] = await surface.extract(target)
                steps.append(step)
                history.append(decision)
                evidence.event("discovery.acted", step_id=step.id, action=action)
            else:
                raise RuntimeError("Discovery exceeded maximum steps")

            # Special-cased, not derived uniformly: the existing demo capability keeps its
            # original id regardless of this change, so nothing already committed (dashboard
            # defaults, docs, prior artifacts) is disrupted. Only a genuinely different
            # system_identifier gets a derived id, which is what lets it coexist as its own,
            # independently discoverable/approvable capability.
            artifact_id = (
                f"lookup-savings-balance-{system_identifier}"
                if system_identifier and system_identifier != "legacy-member-servicing-demo"
                else "lookup-member-savings-balance"
            )
            inputs = [
                ParameterSpec(
                    name="memberId",
                    type="string",
                    description="Demo member identifier",
                    pattern=r"^\d{5}$",
                )
            ] + self._credential_input_specs(extra_known_values)
            artifact = CapabilityArtifact(
                id=artifact_id,
                name="Lookup member savings balance",
                description="Find a member in the legacy demo app and return the savings balance.",
                application=ApplicationBinding(
                    vendor="Interface Demo", product="Legacy Member Servicing", base_url=target_url
                ),
                inputs=inputs,
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

    @staticmethod
    def _resolve_placeholder(value: str | None, known_values: dict[str, str]) -> str:
        """The inverse of the templating comparison above: given a (possibly just-templated)
        decision value, return the real literal to actually type into the browser during
        discovery. Generalizes the old memberId-only re-derivation to any known placeholder."""
        for placeholder_name, literal in known_values.items():
            if value == f"{{{{{placeholder_name}}}}}":
                return literal
        return value or ""

    @staticmethod
    def _credential_input_specs(extra_known_values: dict[str, str] | None) -> list[ParameterSpec]:
        """One ParameterSpec per extra_known_values key -- covers credentials auth (username,
        password) and api_key auth (apiKey) alike with the same logic, no per-auth-type
        branching. "username" is the one name never marked sensitive; every other credential
        name (password, apiKey, or any future one) is."""
        return [
            ParameterSpec(
                name=credential_name,
                type="string",
                description=f"Login credential ({credential_name}) for the target legacy application",
                sensitive=(credential_name != "username"),
            )
            for credential_name in (extra_known_values or {})
        ]

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
