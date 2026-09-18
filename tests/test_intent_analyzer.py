import pytest

from capability_platform.agent.intent_analyzer import IntentAnalysisError, IntentAnalyzer
from capability_platform.llm.mock_provider import MockLLMProvider
from capability_platform.models import RiskLevel
from capability_platform.settings import settings
from capability_platform.validation import GoalTooLongError

SAVINGS_BALANCE_RESPONSE = {
    "intent": "retrieve_account_balance",
    "domain": "member_servicing",
    "operation": "read",
    "entities": [
        {"name": "memberId", "value": "10002", "type": "string"},
        {"name": "accountType", "value": "savings", "type": "string"},
    ],
    "required_outputs": [{"name": "savingsBalance", "type": "number"}],
    "risk": "read_only",
    "confidence": 0.95,
}


async def test_natural_language_maps_to_retrieve_account_balance():
    analyzer = IntentAnalyzer(MockLLMProvider(SAVINGS_BALANCE_RESPONSE))
    intent = await analyzer.analyze("Get the savings balance for member 10002")
    assert intent.intent == "retrieve_account_balance"


async def test_member_id_extracted():
    analyzer = IntentAnalyzer(MockLLMProvider(SAVINGS_BALANCE_RESPONSE))
    intent = await analyzer.analyze("Get the savings balance for member 10002")
    assert intent.entity("memberId") == "10002"


async def test_savings_account_type_extracted():
    analyzer = IntentAnalyzer(MockLLMProvider(SAVINGS_BALANCE_RESPONSE))
    intent = await analyzer.analyze("Get the savings balance for member 10002")
    assert intent.entity("accountType") == "savings"


async def test_required_output_is_savings_balance():
    analyzer = IntentAnalyzer(MockLLMProvider(SAVINGS_BALANCE_RESPONSE))
    intent = await analyzer.analyze("Get the savings balance for member 10002")
    assert [o.name for o in intent.required_outputs] == ["savingsBalance"]


async def test_read_only_risk_assigned():
    analyzer = IntentAnalyzer(MockLLMProvider(SAVINGS_BALANCE_RESPONSE))
    intent = await analyzer.analyze("Get the savings balance for member 10002")
    assert intent.risk == RiskLevel.READ_ONLY


async def test_mock_provider_is_deterministic_across_calls():
    analyzer = IntentAnalyzer(MockLLMProvider(SAVINGS_BALANCE_RESPONSE))
    first = await analyzer.analyze("Get the savings balance for member 10002")
    second = await analyzer.analyze("Get the savings balance for member 10002")
    assert first.model_dump(exclude={"raw_goal"}) == second.model_dump(exclude={"raw_goal"})


async def test_intent_analyzer_never_executes_anything():
    # The analyzer has no executor/registry dependency at all -- there is no method on it other
    # than analyze(), which returns a TaskIntent and nothing else.
    analyzer = IntentAnalyzer(MockLLMProvider(SAVINGS_BALANCE_RESPONSE))
    public_methods = [m for m in dir(analyzer) if not m.startswith("_")]
    assert public_methods == ["analyze", "fallback_provider", "provider"]


async def test_falls_back_to_second_provider_on_error():
    def _raise(*_args):
        raise RuntimeError("primary provider unavailable")

    analyzer = IntentAnalyzer(
        provider=MockLLMProvider(_raise),
        fallback_provider=MockLLMProvider(SAVINGS_BALANCE_RESPONSE),
    )
    intent = await analyzer.analyze("Get the savings balance for member 10002")
    assert intent.intent == "retrieve_account_balance"
    assert intent.provider == "mock:v1"


async def test_raises_when_provider_response_fails_validation():
    analyzer = IntentAnalyzer(MockLLMProvider({"intent": "x"}))  # missing required fields
    with pytest.raises(IntentAnalysisError):
        await analyzer.analyze("do something")


COMPOUND_GOAL_RESPONSE = {
    "intent": "retrieve_balance_and_create_note",
    "domain": "member_servicing",
    "operation": "write",
    "entities": [{"name": "memberId", "value": "10001", "type": "string"}],
    "required_outputs": [
        {"name": "savingsBalance", "type": "number"},
        {"name": "noteId", "type": "string"},
    ],
    "risk": "reversible",
    "confidence": 0.85,
    "sub_goals": [
        {
            "description": "Look up member 10001.",
            "operation": "read",
            "required_inputs": ["memberId"],
            "produced_outputs": ["memberFound"],
        },
        {
            "description": "Retrieve the member's savings account balance.",
            "operation": "read",
            "required_inputs": ["memberId"],
            "produced_outputs": ["savingsBalance"],
        },
        {
            "description": "Create a servicing note on the member's account.",
            "operation": "write",
            "required_inputs": ["memberId", "note"],
            "produced_outputs": ["noteId"],
        },
    ],
}


async def test_sub_goals_round_trip_from_provider_response():
    analyzer = IntentAnalyzer(MockLLMProvider(COMPOUND_GOAL_RESPONSE))
    intent = await analyzer.analyze(
        "Find member 10001, retrieve the savings balance, and create a servicing note"
    )
    assert len(intent.sub_goals) == 3
    assert [sg.operation for sg in intent.sub_goals] == ["read", "read", "write"]
    assert intent.sub_goals[2].required_inputs == ["memberId", "note"]


async def test_sub_goals_default_to_empty_for_a_single_action_goal():
    analyzer = IntentAnalyzer(MockLLMProvider(SAVINGS_BALANCE_RESPONSE))
    intent = await analyzer.analyze("Get the savings balance for member 10002")
    assert intent.sub_goals == []


AMBIGUOUS_GOAL_RESPONSE = {
    "intent": "unknown",
    "domain": "unknown",
    "operation": "read",
    "risk": "read_only",
    "confidence": 0.1,
    "requires_clarification": True,
    "clarification_question": "Which member, and what would you like to do for them?",
}


async def test_requires_clarification_round_trips_from_provider_response():
    analyzer = IntentAnalyzer(MockLLMProvider(AMBIGUOUS_GOAL_RESPONSE))
    intent = await analyzer.analyze("Handle this member.")
    assert intent.requires_clarification is True
    assert intent.clarification_question == "Which member, and what would you like to do for them?"


async def test_requires_clarification_defaults_to_false():
    analyzer = IntentAnalyzer(MockLLMProvider(SAVINGS_BALANCE_RESPONSE))
    intent = await analyzer.analyze("Get the savings balance for member 10002")
    assert intent.requires_clarification is False
    assert intent.clarification_question is None


async def test_analyze_rejects_a_goal_over_the_length_limit():
    analyzer = IntentAnalyzer(MockLLMProvider(SAVINGS_BALANCE_RESPONSE))
    too_long_goal = "x" * (settings.max_goal_length + 1)
    with pytest.raises(GoalTooLongError):
        await analyzer.analyze(too_long_goal)
