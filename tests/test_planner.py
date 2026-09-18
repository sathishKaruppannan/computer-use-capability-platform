from capability_platform.agent.models import RequiredOutput, TaskIntent
from capability_platform.agent.planner import Planner
from capability_platform.models import RiskLevel


def _intent(intent: str, raw_goal: str, entities=(), required_outputs=(), operation="read") -> TaskIntent:
    return TaskIntent(
        intent=intent,
        domain="member_servicing",
        operation=operation,
        entities=list(entities),
        required_outputs=list(required_outputs),
        risk=RiskLevel.READ_ONLY,
        confidence=0.9,
        raw_goal=raw_goal,
        provider="mock:v1",
    )


def test_single_step_plan_has_exact_execution_inputs_only():
    intent = _intent("retrieve_account_balance", "Get the savings balance for member 10002")
    plan = Planner().plan(intent)
    assert len(plan.steps) == 1
    # memberId only -- accountType (an intent entity, not part of the artifact's input schema)
    # must never appear here, or the resolver would reject the real capability.
    assert plan.steps[0].required_inputs == ["memberId"]
    assert plan.steps[0].produced_outputs == ["savingsBalance"]


def test_multi_step_plan_preserves_dependencies():
    intent = _intent(
        "member_lookup_balance_and_note",
        "Find member 10001, retrieve the savings balance, and create a servicing note",
    )
    plan = Planner().plan(intent)
    assert [step.id for step in plan.steps] == ["step-1", "step-2", "step-3"]
    assert plan.steps[0].depends_on == []
    assert plan.steps[1].depends_on == ["step-1"]
    assert plan.steps[2].depends_on == ["step-2"]
    assert plan.steps[2].operation == "write"


def test_unknown_intent_falls_back_to_one_generic_step():
    intent = _intent(
        "open_account_preferences_page",
        "Find member 10001 and open the account preferences page",
        entities=[{"name": "memberId", "value": "10001"}],
        required_outputs=[RequiredOutput(name="confirmation")],
    )
    plan = Planner().plan(intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].required_inputs == ["memberId"]
    assert plan.steps[0].produced_outputs == ["confirmation"]


def test_planner_never_executes_anything():
    public_methods = [m for m in dir(Planner()) if not m.startswith("_")]
    assert public_methods == ["plan"]
