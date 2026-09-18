import pytest

from capability_platform.agent.intent_analyzer import IntentAnalysisError, IntentAnalyzer
from capability_platform.llm.mock_provider import MockLLMProvider
from capability_platform.models import RiskLevel

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
