"""config/policy.json must actually drive PolicyEngine behavior, not just document it."""

import json
from pathlib import Path

import pytest

from capability_platform.policy.engine import PolicyEngine, PolicyViolation, default_policy


def test_default_policy_loads_the_real_config_file():
    policy = default_policy()
    real_config = json.loads(Path("config/policy.json").read_text(encoding="utf-8"))
    assert policy.allowed_hosts == frozenset(real_config["allowedHosts"])


def test_editing_policy_json_changes_authorized_hosts(tmp_path):
    custom_path = tmp_path / "policy.json"
    custom_path.write_text(
        json.dumps(
            {
                "allowedHosts": ["only-this-host.example"],
                "allowedActions": ["navigate", "click", "type", "select", "wait", "extract", "assert"],
                "maxRiskWithoutApproval": "reversible",
            }
        ),
        encoding="utf-8",
    )
    policy = default_policy(custom_path)
    engine = PolicyEngine(policy)

    with pytest.raises(PolicyViolation):
        engine.authorize_url("http://127.0.0.1:8001")  # allowed by the real config, not this one

    engine.authorize_url("http://only-this-host.example")  # must not raise
