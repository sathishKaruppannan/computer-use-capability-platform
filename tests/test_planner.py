from capability_platform.agent.models import RequiredOutput, SubGoal, TaskIntent
from capability_platform.agent.planner import Planner
from capability_platform.models import RiskLevel


def _intent(
    intent: str, raw_goal: str, entities=(), required_outputs=(), operation="read", sub_goals=()
) -> TaskIntent:
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
        sub_goals=list(sub_goals),
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


def test_sub_goals_produce_sequentially_dependent_steps():
    """The general mechanism: a compound goal's LLM-identified sub_goals (not a hardcoded
    template key) drive multi-step decomposition -- this is what makes example 3 work for a
    genuinely novel compound goal, not just the one hardcoded 'member_lookup_balance_and_note'
    intent id from the old template-only design."""
    intent = _intent(
        "retrieve_balance_and_create_note",
        "Find member 10001, retrieve the savings balance, and create a servicing note",
        operation="write",
        sub_goals=[
            SubGoal(
                description="Look up member 10001.",
                operation="read",
                required_inputs=["memberId"],
                produced_outputs=["memberFound"],
            ),
            SubGoal(
                description="Retrieve the member's savings account balance.",
                operation="read",
                required_inputs=["memberId"],
                produced_outputs=["savingsBalance"],
            ),
            SubGoal(
                description="Create a servicing note on the member's account.",
                operation="write",
                required_inputs=["memberId", "note"],
                produced_outputs=["noteId"],
            ),
        ],
    )
    plan = Planner().plan(intent)

    assert [step.id for step in plan.steps] == ["step-1", "step-2", "step-3"]
    assert plan.steps[0].depends_on == []
    assert plan.steps[1].depends_on == ["step-1"]
    assert plan.steps[2].depends_on == ["step-2"]
    assert plan.steps[0].risk == RiskLevel.READ_ONLY
    assert plan.steps[2].risk == RiskLevel.REVERSIBLE
    assert plan.steps[2].operation == "write"
    assert plan.steps[2].required_inputs == ["memberId", "note"]


def test_sub_goals_take_priority_over_a_matching_template():
    """Even when intent.intent happens to match a registered template, a non-empty sub_goals
    list wins -- it's the more specific, goal-tailored decomposition."""
    intent = _intent(
        "retrieve_account_balance",
        "Get the savings balance for member 10002",
        sub_goals=[
            SubGoal(
                description="Retrieve the balance a different way.",
                operation="read",
                required_inputs=["memberId"],
                produced_outputs=["savingsBalance"],
            )
        ],
    )
    plan = Planner().plan(intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].description == "Retrieve the balance a different way."


def test_empty_sub_goals_falls_back_to_existing_template_behavior():
    intent = _intent("retrieve_account_balance", "Get the savings balance for member 10002")
    plan = Planner().plan(intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].required_inputs == ["memberId"]
