"""Layer 2: TaskIntent -> ExecutionPlan. Deterministic, no LLM call, never executes a tool --
just declares what needs to happen, in what order, with what data flowing between steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from capability_platform.agent.models import ExecutionPlan, PlanStep, TaskIntent
from capability_platform.models import RiskLevel


@dataclass(frozen=True)
class StepTemplate:
    id: str
    description: str
    operation: Literal["read", "write"]
    required_inputs: tuple[str, ...]
    produced_outputs: tuple[str, ...]
    depends_on: tuple[str, ...]
    risk: RiskLevel


# Templates are keyed by TaskIntent.intent. required_inputs/produced_outputs here are strictly
# the EXECUTION contract a capability must satisfy -- not every TaskIntent entity belongs in
# required_inputs. Concretely: the committed artifact `lookup-member-savings-balance.v1.json`
# declares only `memberId` as an input, so the retrieve_account_balance template's
# required_inputs must be exactly that -- `accountType` stays a TaskIntent entity (useful for
# routing/description) but is never added here, or the resolver's exact-input-compatibility
# check would reject the very capability this template exists to select.
PLAN_TEMPLATES: dict[str, tuple[StepTemplate, ...]] = {
    "retrieve_account_balance": (
        StepTemplate(
            id="step-1",
            description="Look up the member and retrieve their savings account balance.",
            operation="read",
            required_inputs=("memberId",),
            produced_outputs=("savingsBalance",),
            depends_on=(),
            risk=RiskLevel.READ_ONLY,
        ),
    ),
    # Illustrative 3-step decomposition (lookup / retrieve balance / create servicing note).
    # step-1 and step-3 have no matching deterministic capability today and are expected to
    # resolve to COMPUTER_USE_DISCOVERY -- exactly the heterogeneous-resolution behavior the
    # capability resolver is meant to demonstrate.
    "member_lookup_balance_and_note": (
        StepTemplate(
            id="step-1",
            description="Look up the member.",
            operation="read",
            required_inputs=("memberId",),
            produced_outputs=("memberFound",),
            depends_on=(),
            risk=RiskLevel.READ_ONLY,
        ),
        StepTemplate(
            id="step-2",
            description="Retrieve the member's savings account balance.",
            operation="read",
            required_inputs=("memberId",),
            produced_outputs=("savingsBalance",),
            depends_on=("step-1",),
            risk=RiskLevel.READ_ONLY,
        ),
        StepTemplate(
            id="step-3",
            description="Create a servicing note on the member's account.",
            operation="write",
            required_inputs=("memberId", "note"),
            produced_outputs=("noteId",),
            depends_on=("step-2",),
            risk=RiskLevel.REVERSIBLE,
        ),
    ),
}


class Planner:
    def plan(self, intent: TaskIntent) -> ExecutionPlan:
        if intent.sub_goals:
            # A compound goal the Intent Analyzer's own LLM call already decomposed -- takes
            # priority over PLAN_TEMPLATES, since it's a more specific, goal-tailored
            # decomposition than any fixed template could be. The Planner stays LLM-free here:
            # it just mechanically turns an already-ordered list into sequential PlanSteps.
            steps = self._steps_from_sub_goals(intent)
        else:
            templates = PLAN_TEMPLATES.get(intent.intent) or self._fallback_templates(intent)
            steps = [
                PlanStep(
                    id=template.id,
                    description=template.description,
                    operation=template.operation,
                    required_inputs=list(template.required_inputs),
                    produced_outputs=list(template.produced_outputs),
                    depends_on=list(template.depends_on),
                    risk=template.risk,
                    intent_ref=intent.intent,
                )
                for template in templates
            ]
        return ExecutionPlan(id=str(uuid4()), goal=intent.raw_goal, steps=steps)

    @staticmethod
    def _steps_from_sub_goals(intent: TaskIntent) -> list[PlanStep]:
        """One PlanStep per SubGoal, in the order the Intent Analyzer declared them, chained
        sequentially (step-N depends on step-(N-1)) -- the LLM call already established
        execution order; the Planner just mechanically turns that into dependency edges. Risk is
        still assigned code-side (read -> READ_ONLY, write -> REVERSIBLE), never taken from the
        model, matching the same "risk is never model-decided" rule discovery.py already follows."""
        steps: list[PlanStep] = []
        for index, sub_goal in enumerate(intent.sub_goals, start=1):
            steps.append(
                PlanStep(
                    id=f"step-{index}",
                    description=sub_goal.description,
                    operation=sub_goal.operation,
                    required_inputs=list(sub_goal.required_inputs),
                    produced_outputs=list(sub_goal.produced_outputs),
                    depends_on=[f"step-{index - 1}"] if index > 1 else [],
                    risk=RiskLevel.READ_ONLY if sub_goal.operation == "read" else RiskLevel.REVERSIBLE,
                    intent_ref=intent.intent,
                )
            )
        return steps

    @staticmethod
    def _fallback_templates(intent: TaskIntent) -> tuple[StepTemplate, ...]:
        """An intent with no known template (including an "unknown" intent) becomes one generic
        step wrapping the whole goal, whose required_inputs/produced_outputs come straight from
        the intent's own entities/required_outputs. The resolver's own fallback-to-discovery
        handles it from there without the planner needing to understand the domain."""
        return (
            StepTemplate(
                id="step-1",
                description=f"Accomplish: {intent.raw_goal}",
                operation=intent.operation,
                required_inputs=tuple(entity.name for entity in intent.entities),
                produced_outputs=tuple(output.name for output in intent.required_outputs),
                depends_on=(),
                risk=intent.risk,
            ),
        )
