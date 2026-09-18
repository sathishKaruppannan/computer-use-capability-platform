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


def test_credential_input_specs_none_when_no_auth():
    assert ClaudeDiscoveryAgent._credential_input_specs(None) == []
    assert ClaudeDiscoveryAgent._credential_input_specs({}) == []


def test_credential_input_specs_for_credentials_auth():
    specs = ClaudeDiscoveryAgent._credential_input_specs(
        {"username": "demo", "password": "letmein-2024"}
    )
    by_name = {s.name: s for s in specs}
    assert by_name["username"].sensitive is False
    assert by_name["password"].sensitive is True


def test_credential_input_specs_for_api_key_auth():
    specs = ClaudeDiscoveryAgent._credential_input_specs({"apiKey": "sk-demo-abc123"})
    assert len(specs) == 1
    assert specs[0].name == "apiKey"
    assert specs[0].sensitive is True


def test_slugify_converts_snake_case_intent_to_dash_separated_id():
    assert ClaudeDiscoveryAgent._slugify("retrieve_account_balance") == "retrieve-account-balance"


def test_slugify_strips_non_alphanumeric_and_lowercases():
    assert ClaudeDiscoveryAgent._slugify("Confirm Member's Status!") == "confirm-member-s-status"


def test_derive_tags_falls_back_to_savings_balance_defaults_when_no_hint():
    assert ClaudeDiscoveryAgent._derive_tags(None) == ["member", "savings", "balance", "computer-use"]


def test_derive_tags_from_capability_hint():
    tags = ClaudeDiscoveryAgent._derive_tags("confirm_account_status")
    assert tags == ["confirm", "account", "status", "computer-use"]
