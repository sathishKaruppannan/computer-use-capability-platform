"""Prompt versioning (T: production discover/mock-demo prompt selection). Constructing
ClaudeDiscoveryAgent only builds an AsyncAnthropic client object — it never makes a network
call — so these run as plain unit tests, no API key or live browser needed."""

import pytest

from capability_platform.agent.discovery import ClaudeDiscoveryAgent
from capability_platform.agent.prompts.registry import get_prompt_variant


def test_production_and_demo_variants_differ_in_prose_but_share_the_tool_schema():
    production = get_prompt_variant("production")
    demo = get_prompt_variant("demo")

    assert production.system_prompt != demo.system_prompt
    assert production.action_tool.keys() == demo.action_tool.keys()
    assert production.action_tool == demo.action_tool


def test_unknown_prompt_variant_raises():
    with pytest.raises(ValueError, match="Unknown prompt variant"):
        get_prompt_variant("nonexistent")


def test_qualified_id_mirrors_capability_artifact_versioning_convention():
    assert get_prompt_variant("production").qualified_id == "production.v1"
    assert get_prompt_variant("demo").qualified_id == "demo.v1"


def test_discovery_agent_defaults_to_production_prompt():
    agent = ClaudeDiscoveryAgent("fake-key", "fake-model", None, None)
    assert agent.prompt.id == "production"


def test_discovery_agent_accepts_demo_prompt_variant():
    agent = ClaudeDiscoveryAgent("fake-key", "fake-model", None, None, prompt_variant="demo")
    assert agent.prompt.id == "demo"


def test_discovery_agent_rejects_unknown_prompt_variant():
    with pytest.raises(ValueError, match="Unknown prompt variant"):
        ClaudeDiscoveryAgent("fake-key", "fake-model", None, None, prompt_variant="nonexistent")
