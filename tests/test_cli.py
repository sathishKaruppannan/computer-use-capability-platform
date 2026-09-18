import argparse

from capability_platform.cli import build_goal_context, parse_inputs


def test_parse_inputs_splits_key_value_pairs():
    assert parse_inputs(["memberId=10002", "accountType=savings"]) == {
        "memberId": "10002",
        "accountType": "savings",
    }


def test_build_goal_context_includes_target_url_when_supplied():
    args = argparse.Namespace(context=["memberId=10002"], target_url="http://127.0.0.1:8001/secure")
    context = build_goal_context(args)
    assert context == {"memberId": "10002", "target_url": "http://127.0.0.1:8001/secure"}


def test_build_goal_context_omits_target_url_when_not_supplied():
    args = argparse.Namespace(context=["memberId=10002"], target_url=None)
    context = build_goal_context(args)
    assert context == {"memberId": "10002"}


def test_build_goal_context_works_without_a_target_url_attribute_at_all():
    """discover/replay/list/approve/register-client subcommands have no --target-url flag at
    all -- build_goal_context must not assume the attribute exists."""
    args = argparse.Namespace(context=[])
    assert build_goal_context(args) == {}
