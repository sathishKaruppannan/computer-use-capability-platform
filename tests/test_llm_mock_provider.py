from capability_platform.llm.mock_provider import MockLLMProvider


async def test_static_dict_response_is_returned_verbatim():
    provider = MockLLMProvider({"intent": "retrieve_account_balance"})
    result = await provider.complete_json("system", "user", {"type": "object"})
    assert result == {"intent": "retrieve_account_balance"}


async def test_callable_responder_receives_the_prompts_and_schema():
    seen = {}

    def responder(system_prompt, user_prompt, json_schema):
        seen["system_prompt"] = system_prompt
        seen["user_prompt"] = user_prompt
        seen["json_schema"] = json_schema
        return {"ok": True}

    provider = MockLLMProvider(responder)
    result = await provider.complete_json("sys", "usr", {"type": "object"})
    assert result == {"ok": True}
    assert seen == {"system_prompt": "sys", "user_prompt": "usr", "json_schema": {"type": "object"}}


async def test_repeated_calls_are_deterministic():
    provider = MockLLMProvider({"a": 1})
    first = await provider.complete_json("s", "u", {})
    second = await provider.complete_json("s", "u", {})
    assert first == second
