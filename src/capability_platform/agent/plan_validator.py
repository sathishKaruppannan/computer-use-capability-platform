"""Layer 3: validates an ExecutionPlan before any step is resolved/executed. Reuses the
existing, unmodified PolicyEngine for risk/approval -- no second policy system."""

from __future__ import annotations

from collections.abc import Iterable

from capability_platform.agent.models import ExecutionPlan, PlanStep
from capability_platform.models import ActionType, Step
from capability_platform.policy.engine import PolicyEngine


class PlanValidationError(RuntimeError):
    """Hard rejection of a malformed, cyclic, or under-specified plan. Fail closed."""


class PlanValidator:
    def __init__(self, policy: PolicyEngine) -> None:
        self.policy = policy

    def validate(self, plan: ExecutionPlan, known_inputs: Iterable[str] = ()) -> list[str]:
        """Raises PlanValidationError on hard rejection. Returns the step_ids that require human
        approval before execution -- informational; actual gating still happens, unchanged, at
        execution time via PolicyEngine/the intervention mechanism."""
        if not plan.steps:
            raise PlanValidationError("Plan has no steps")

        ids = [step.id for step in plan.steps]
        if len(ids) != len(set(ids)):
            raise PlanValidationError(f"Plan has duplicate step ids: {ids}")

        by_id = {step.id: step for step in plan.steps}
        for step in plan.steps:
            for dep in step.depends_on:
                if dep not in by_id:
                    raise PlanValidationError(f"Step '{step.id}' depends on unknown step '{dep}'")

        self._check_cycles(by_id)
        self._check_missing_inputs(plan, by_id, set(known_inputs))

        requires_approval: list[str] = []
        for step in plan.steps:
            throwaway = Step(
                id=step.id, action=ActionType.ASSERT, description=step.description, risk=step.risk
            )
            if self.policy.requires_approval(throwaway):
                requires_approval.append(step.id)
        return requires_approval

    @staticmethod
    def _check_cycles(by_id: dict[str, PlanStep]) -> None:
        white, gray, black = 0, 1, 2
        color = dict.fromkeys(by_id, white)

        def visit(step_id: str, path: list[str]) -> None:
            color[step_id] = gray
            for dep in by_id[step_id].depends_on:
                if color[dep] == gray:
                    raise PlanValidationError(f"Cyclic dependency detected: {' -> '.join([*path, dep])}")
                if color[dep] == white:
                    visit(dep, [*path, dep])
            color[step_id] = black

        for step_id in by_id:
            if color[step_id] == white:
                visit(step_id, [step_id])

    @staticmethod
    def _transitive_upstream_outputs(step: PlanStep, by_id: dict[str, PlanStep]) -> set[str]:
        seen: set[str] = set()
        outputs: set[str] = set()
        stack = list(step.depends_on)
        while stack:
            dep_id = stack.pop()
            if dep_id in seen:
                continue
            seen.add(dep_id)
            dep = by_id[dep_id]
            outputs.update(dep.produced_outputs)
            stack.extend(dep.depends_on)
        return outputs

    def _check_missing_inputs(
        self, plan: ExecutionPlan, by_id: dict[str, PlanStep], known_inputs: set[str]
    ) -> None:
        for step in plan.steps:
            available = known_inputs | self._transitive_upstream_outputs(step, by_id)
            missing = [name for name in step.required_inputs if name not in available]
            if missing:
                raise PlanValidationError(f"Step '{step.id}' is missing required inputs: {missing}")
