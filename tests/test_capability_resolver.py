from pathlib import Path

from capability_platform.agent.models import PlanStep, ResolutionType
from capability_platform.capabilities.registry import CapabilityRegistry, build_registry
from capability_platform.capabilities.resolver import CapabilityResolver
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.models import CapabilityDescriptor, RiskLevel
from capability_platform.policy.engine import PolicyEngine, default_policy


def _balance_step(step_id: str = "step-1") -> PlanStep:
    return PlanStep(
        id=step_id,
        description="Look up the member and retrieve their savings account balance.",
        operation="read",
        required_inputs=["memberId"],
        produced_outputs=["savingsBalance"],
        depends_on=[],
        risk=RiskLevel.READ_ONLY,
        intent_ref="retrieve_account_balance",
    )


def _resolver(registry: CapabilityRegistry) -> CapabilityResolver:
    return CapabilityResolver(registry, ArtifactStore(Path("artifacts")), PolicyEngine(default_policy()))


def test_existing_capability_is_selected_over_discovery():
    registry = build_registry(ArtifactStore(Path("artifacts")))
    resolution = _resolver(registry).resolve(_balance_step())
    assert resolution.resolution_type == ResolutionType.COMPUTER_USE_CAPABILITY
    assert resolution.selected is not None
    assert resolution.selected.descriptor.id == "lookup-member-savings-balance.v1"


def test_unmatched_step_falls_back_to_computer_use_discovery(seeded_capability_registry):
    step = PlanStep(
        id="step-1",
        description="Open the account preferences page.",
        operation="read",
        required_inputs=["memberId"],
        produced_outputs=["confirmation"],
        depends_on=[],
        risk=RiskLevel.READ_ONLY,
        intent_ref="open_account_preferences_page",
    )
    resolution = _resolver(seeded_capability_registry).resolve(step)
    assert resolution.resolution_type == ResolutionType.COMPUTER_USE_DISCOVERY
    assert resolution.discovery_goal == step.description


def test_unmatched_step_resolves_unresolved_when_discovery_disabled(seeded_capability_registry):
    step = PlanStep(
        id="step-1",
        description="Open the account preferences page.",
        operation="read",
        required_inputs=["memberId"],
        produced_outputs=["confirmation"],
        depends_on=[],
        risk=RiskLevel.READ_ONLY,
        intent_ref="open_account_preferences_page",
    )
    resolution = _resolver(seeded_capability_registry).resolve(step, context={"allow_discovery": False})
    assert resolution.resolution_type == ResolutionType.UNRESOLVED


def test_blocked_mcp_capability_is_never_selected(seeded_capability_registry):
    resolution = _resolver(seeded_capability_registry).resolve(_balance_step())
    assert resolution.selected.descriptor.id != "blocked-savings-balance-mcp"
    assert all(c.descriptor.id != "blocked-savings-balance-mcp" for c in resolution.alternatives)


def test_unapproved_capability_is_never_selected(seeded_capability_registry):
    resolution = _resolver(seeded_capability_registry).resolve(_balance_step())
    assert resolution.selected.descriptor.id != "discovered-savings-balance"


def test_input_incompatible_capability_is_rejected():
    registry = CapabilityRegistry(
        [
            CapabilityDescriptor(
                id="wrong-input-schema",
                name="Wrong input schema",
                description="Look up a member's savings balance",
                source="local_tool",
                input_schema={"accountNumber": {"type": "string", "required": True}},
                output_schema={"savingsBalance": {"type": "number"}},
                risk=RiskLevel.READ_ONLY,
                trust="approved",
                reliability=1.0,
                tags=["member", "savings", "balance"],
            )
        ]
    )
    resolution = _resolver(registry).resolve(_balance_step(), context={"allow_discovery": False})
    assert resolution.resolution_type == ResolutionType.UNRESOLVED
    [candidate] = resolution.alternatives
    assert candidate.input_compatible is False
    assert candidate.output_compatible is True
    assert "required inputs" in candidate.rejection_reasons[0]


def test_output_incompatible_capability_is_rejected():
    registry = CapabilityRegistry(
        [
            CapabilityDescriptor(
                id="wrong-output-schema",
                name="Wrong output schema",
                description="Look up a member's savings balance",
                source="local_tool",
                input_schema={"memberId": {"type": "string", "required": True}},
                output_schema={"currentBalance": {"type": "number"}},
                risk=RiskLevel.READ_ONLY,
                trust="approved",
                reliability=1.0,
                tags=["member", "savings", "balance"],
            )
        ]
    )
    resolution = _resolver(registry).resolve(_balance_step(), context={"allow_discovery": False})
    assert resolution.resolution_type == ResolutionType.UNRESOLVED
    [candidate] = resolution.alternatives
    assert candidate.input_compatible is True
    assert candidate.output_compatible is False
    assert "produced outputs" in candidate.rejection_reasons[0]


def test_extra_required_input_the_step_cannot_supply_is_rejected():
    """A capability needing MORE inputs than the step declares must not be selected just because
    it also accepts memberId -- unless that extra input is a known credential field name
    (username/password), which is satisfiable via the per-client TenantCredentialStore at
    execution time, not something the plan step needs to declare in advance."""
    registry = CapabilityRegistry(
        [
            CapabilityDescriptor(
                id="needs-account-number",
                name="Savings balance lookup requiring an unrelated extra field",
                description="Look up a member's savings balance",
                source="computer_use",
                input_schema={
                    "memberId": {"type": "string", "required": True},
                    "accountNumber": {"type": "string", "required": True},
                },
                output_schema={"savingsBalance": {"type": "number"}},
                risk=RiskLevel.READ_ONLY,
                trust="approved",
                reliability=1.0,
                tags=["member", "savings", "balance"],
            )
        ]
    )
    resolution = _resolver(registry).resolve(_balance_step(), context={"allow_discovery": False})
    assert resolution.resolution_type == ResolutionType.UNRESOLVED
    [candidate] = resolution.alternatives
    assert candidate.input_compatible is False


def test_login_gated_capability_is_input_compatible_via_credential_store():
    """The credential-store design point: a login-gated capability needing username/password
    beyond what the step declares IS input-compatible (those fields are pulled from
    TenantCredentialStore at execution time), even though it still isn't SELECTED over a
    credential-free alternative when both are otherwise equal (see the real-artifacts resolver
    test above, which proves lookup-member-savings-balance.v1 still wins the tie-break)."""
    registry = CapabilityRegistry(
        [
            CapabilityDescriptor(
                id="needs-credentials",
                name="Login-gated savings balance lookup",
                description="Look up a member's savings balance behind a login",
                source="computer_use",
                input_schema={
                    "memberId": {"type": "string", "required": True},
                    "username": {"type": "string", "required": True},
                    "password": {"type": "string", "required": True},
                },
                output_schema={"savingsBalance": {"type": "number"}},
                risk=RiskLevel.READ_ONLY,
                trust="approved",
                reliability=1.0,
                tags=["member", "savings", "balance"],
            )
        ]
    )
    resolution = _resolver(registry).resolve(_balance_step(), context={"allow_discovery": False})
    # Still UNRESOLVED overall in this isolated test -- the descriptor id isn't a real artifact
    # on disk, so _policy_ok's authorize_url check fails for an unrelated reason. The point under
    # test is specifically input_compatible, asserted directly below.
    [candidate] = resolution.alternatives
    assert candidate.input_compatible is True
