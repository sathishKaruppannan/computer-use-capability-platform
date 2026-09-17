"""Unit coverage of ClaudeDiscoveryAgent's placeholder resolution -- the generalized (memberId,
username, password, ...) version of the templating logic, in isolation from Playwright/Anthropic.
ClaudeDiscoveryAgent._resolve_placeholder is a @staticmethod, directly callable with no agent
instance needed."""

from capability_platform.agent.discovery import ClaudeDiscoveryAgent


def test_resolve_placeholder_returns_literal_for_known_placeholder():
    known_values = {"memberId": "10001", "username": "demo", "password": "letmein-2024"}
    assert ClaudeDiscoveryAgent._resolve_placeholder("{{memberId}}", known_values) == "10001"
    assert ClaudeDiscoveryAgent._resolve_placeholder("{{username}}", known_values) == "demo"
    assert (
        ClaudeDiscoveryAgent._resolve_placeholder("{{password}}", known_values) == "letmein-2024"
    )


def test_resolve_placeholder_passes_through_non_placeholder_values():
    known_values = {"memberId": "10001"}
    assert ClaudeDiscoveryAgent._resolve_placeholder("some other text", known_values) == "some other text"


def test_resolve_placeholder_handles_none():
    assert ClaudeDiscoveryAgent._resolve_placeholder(None, {"memberId": "10001"}) == ""


def test_resolve_placeholder_ignores_unknown_placeholder_syntax():
    # A value that merely looks like a placeholder but isn't a known one is returned as-is,
    # not resolved to empty or raising -- matches the original memberId-only behavior's fallback.
    known_values = {"memberId": "10001"}
    assert (
        ClaudeDiscoveryAgent._resolve_placeholder("{{somethingElse}}", known_values)
        == "{{somethingElse}}"
    )
