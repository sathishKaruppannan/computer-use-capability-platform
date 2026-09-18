import pytest

from capability_platform.agent.models import ExecutionPlan, PlanStep
from capability_platform.agent.plan_validator import PlanValidationError, PlanValidator
from capability_platform.models import RiskLevel
from capability_platform.policy.engine import PolicyEngine, default_policy


def _step(id, required_inputs=(), produced_outputs=(), depends_on=(), risk=RiskLevel.READ_ONLY, operation="read"):
    return PlanStep(
        id=id,
        description=f"step {id}",
        operation=operation,
        required_inputs=list(required_inputs),
        produced_outputs=list(produced_outputs),
        depends_on=list(depends_on),
        risk=risk,
        intent_ref="test_intent",
    )


def _validator() -> PlanValidator:
    return PlanValidator(PolicyEngine(default_policy()))


def test_valid_plan_returns_no_approval_needed_for_read_only_steps():
    plan = ExecutionPlan(id="p1", goal="g", steps=[_step("step-1", required_inputs=["memberId"])])
    assert _validator().validate(plan, known_inputs=["memberId"]) == []


def test_multi_step_plan_with_satisfied_transitive_inputs_is_valid():
    plan = ExecutionPlan(
        id="p1",
        goal="g",
        steps=[
            _step("step-1", required_inputs=["memberId"], produced_outputs=["memberFound"]),
            _step("step-2", required_inputs=["memberFound"], depends_on=["step-1"]),
        ],
    )
    assert _validator().validate(plan, known_inputs=["memberId"]) == []


def test_rejects_cyclic_dependencies():
    plan = ExecutionPlan(
        id="p1",
        goal="g",
        steps=[
            _step("step-1", depends_on=["step-2"]),
            _step("step-2", depends_on=["step-1"]),
        ],
    )
    with pytest.raises(PlanValidationError, match="Cyclic dependency"):
        _validator().validate(plan)


def test_rejects_missing_required_inputs():
    plan = ExecutionPlan(id="p1", goal="g", steps=[_step("step-1", required_inputs=["note"])])
    with pytest.raises(PlanValidationError, match="missing required inputs"):
        _validator().validate(plan, known_inputs=["memberId"])


def test_rejects_dependency_on_unknown_step():
    plan = ExecutionPlan(id="p1", goal="g", steps=[_step("step-1", depends_on=["ghost"])])
    with pytest.raises(PlanValidationError, match="unknown step"):
        _validator().validate(plan)


def test_rejects_duplicate_step_ids():
    plan = ExecutionPlan(id="p1", goal="g", steps=[_step("step-1"), _step("step-1")])
    with pytest.raises(PlanValidationError, match="duplicate step ids"):
        _validator().validate(plan)


def test_rejects_empty_plan():
    plan = ExecutionPlan(id="p1", goal="g", steps=[])
    with pytest.raises(PlanValidationError, match="no steps"):
        _validator().validate(plan)


def test_irreversible_step_requires_approval():
    plan = ExecutionPlan(
        id="p1", goal="g", steps=[_step("step-1", risk=RiskLevel.IRREVERSIBLE, operation="write")]
    )
    assert _validator().validate(plan) == ["step-1"]


def test_only_risky_steps_flagged_others_pass_through():
    plan = ExecutionPlan(
        id="p1",
        goal="g",
        steps=[
            _step("step-1", required_inputs=["memberId"]),
            _step("step-2", risk=RiskLevel.RISKY, operation="write", depends_on=["step-1"]),
        ],
    )
    assert _validator().validate(plan, known_inputs=["memberId"]) == ["step-2"]
