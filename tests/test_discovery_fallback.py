"""OpenAI fallback: if a single Anthropic call errors during discovery, that one decision falls
back to GPT-5 mini instead of aborting the whole run. Claude stays primary — this is never used
while Anthropic is healthy. Uses mocked clients so it runs without real API keys; the real
end-to-end proof (a genuine Anthropic failure + a real GPT-5 mini call) is documented in
evidence/README.md with committed evidence."""

import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from capability_platform.agent.discovery import ClaudeDiscoveryAgent
from capability_platform.observability.evidence import EvidenceCollector
from capability_platform.policy.engine import PolicyEngine, default_policy


def _broken_anthropic_call(*args, **kwargs):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    raise anthropic.APIConnectionError(request=request)


def _openai_tool_response(decision: dict) -> SimpleNamespace:
    tool_call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps(decision)))
    message = SimpleNamespace(tool_calls=[tool_call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _agent(tmp_path, *, with_openai: bool) -> ClaudeDiscoveryAgent:
    return ClaudeDiscoveryAgent(
        api_key="fake-anthropic-key",
        model="claude-sonnet-4-5",
        policy=PolicyEngine(default_policy()),
        evidence_root=tmp_path,
        openai_api_key="fake-openai-key" if with_openai else None,
        openai_model="gpt-5-mini",
    )


async def test_decide_falls_back_to_openai_on_anthropic_error(tmp_path, monkeypatch):
    agent = _agent(tmp_path, with_openai=True)
    expected_decision = {"action": "wait", "reason": "transient load"}

    async def fake_anthropic(*args, **kwargs):
        _broken_anthropic_call()

    async def fake_openai(*args, **kwargs):
        return _openai_tool_response(expected_decision)

    monkeypatch.setattr(agent.client.messages, "create", fake_anthropic)
    monkeypatch.setattr(agent.openai_client.chat.completions, "create", fake_openai)

    evidence = EvidenceCollector(tmp_path, "test-run")
    decision = await agent._decide("goal", {"url": "x"}, [], evidence)

    assert decision == expected_decision
    events = (tmp_path / "runs" / "test-run" / "events.jsonl").read_text(encoding="utf-8")
    assert '"event": "discovery.provider_fallback"' in events
    assert '"to_provider": "openai:gpt-5-mini"' in events


async def test_decide_reraises_when_no_openai_configured(tmp_path, monkeypatch):
    agent = _agent(tmp_path, with_openai=False)

    async def fake_anthropic(*args, **kwargs):
        _broken_anthropic_call()

    monkeypatch.setattr(agent.client.messages, "create", fake_anthropic)

    evidence = EvidenceCollector(tmp_path, "test-run-2")
    with pytest.raises(anthropic.APIConnectionError):
        await agent._decide("goal", {"url": "x"}, [], evidence)


async def test_decide_never_falls_back_when_anthropic_succeeds(tmp_path, monkeypatch):
    """The fallback must not fire when the primary provider is healthy."""
    agent = _agent(tmp_path, with_openai=True)
    expected_decision = {"action": "wait", "reason": "no fallback needed"}

    async def fake_anthropic(*args, **kwargs):
        block = SimpleNamespace(type="tool_use", input=expected_decision)
        return SimpleNamespace(content=[block])

    async def openai_should_not_be_called(*args, **kwargs):
        raise AssertionError("OpenAI must not be called when Anthropic succeeds")

    monkeypatch.setattr(agent.client.messages, "create", fake_anthropic)
    monkeypatch.setattr(agent.openai_client.chat.completions, "create", openai_should_not_be_called)

    evidence = EvidenceCollector(tmp_path, "test-run-3")
    decision = await agent._decide("goal", {"url": "x"}, [], evidence)

    assert decision == expected_decision
    # No fallback means _decide never calls evidence.event(), so the log file may not even
    # exist yet — that absence is itself proof no fallback event was recorded.
    events_path = tmp_path / "runs" / "test-run-3" / "events.jsonl"
    assert not events_path.exists() or "provider_fallback" not in events_path.read_text(
        encoding="utf-8"
    )
