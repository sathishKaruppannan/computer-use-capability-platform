"""Shared construction logic for the two intervention-flow demo capabilities. Both
scripts/debug/create_*_demo_capability.py (one-time terminal step) and api/app.py's
POST /admin/seed-demo-capabilities (the one-click UI equivalent) call these same build_*_demo()
functions, so the artifact-construction logic exists in exactly one place. Neither function calls
store.save() -- callers decide when/whether to persist."""

from capability_platform.capabilities.store import ArtifactStore
from capability_platform.models import (
    CapabilityArtifact,
    Checkpoint,
    ErrorCategory,
    ErrorRule,
    Locator,
    RiskLevel,
    Target,
)

PAUSE_DEMO_ID = "lookup-member-savings-balance-pause-demo"
APPROVAL_DEMO_ID = "lookup-member-savings-balance-approval-demo"


def build_pause_demo(store: ArtifactStore) -> CapabilityArtifact:
    """Same as lookup-member-savings-balance.v1, with a pause-recovery ErrorRule injected onto
    the search step (steps[1]), watching for demo_app's member-10003 "Session Notice"
    interstitial -- drives the human handoff / pause demo."""
    base = store.load("lookup-member-savings-balance.v1")
    demo = base.model_copy(deep=True)
    demo.id = PAUSE_DEMO_ID
    demo.name = "Lookup member savings balance (pause demo)"
    demo.description = (
        "Same as lookup-member-savings-balance.v1, with an injected pause rule for demoing "
        "human handoff live. Not for production use."
    )
    demo.lifecycle = "approved"
    # Deliberately cleared, not copied from base: this is a standalone fixture meant to be
    # invoked only by its own capability_id (see the dashboard's "seed demo capabilities"
    # shortcuts), never through the resolver. Left set, it would collide with the real
    # capability's own (service_type, system_identifier) pair the moment base has been stamped
    # by a real discovery -- ArtifactStore.find_approved_by_service_and_system() would then have
    # two-plus equally-valid approved matches and return whichever ArtifactStore.list() happens
    # to enumerate first (filesystem glob order, not deterministic).
    demo.service_type = None
    demo.system_identifier = None
    demo.steps[1].errors.append(
        ErrorRule(
            code="SESSION_INTERSTITIAL",
            category=ErrorCategory.RECOVERABLE,
            when=Checkpoint(
                kind="visible",
                target=Target(
                    primary=Locator(strategy="text", value="Session Notice", exact=False),
                    rationale="Injected unexpected interstitial for handoff demo",
                ),
            ),
            message="Unexpected session interstitial requires human dismissal",
            recovery="pause",
        )
    )
    return demo


def build_approval_demo(store: ArtifactStore) -> CapabilityArtifact:
    """Same as lookup-member-savings-balance.v1, with steps[2] ("Open Accounts") marked
    risk=RISKY -- above config/policy.json's maxRiskWithoutApproval -- drives the risky-action
    human approval gate demo."""
    base = store.load("lookup-member-savings-balance.v1")
    demo = base.model_copy(deep=True)
    demo.id = APPROVAL_DEMO_ID
    demo.name = "Lookup member savings balance (approval demo)"
    demo.description = (
        "Same as lookup-member-savings-balance.v1, with one step marked risky for demoing the "
        "human approval gate live. Not for production use."
    )
    demo.lifecycle = "approved"
    # Same reasoning as build_pause_demo above -- cleared, not copied, so this never collides
    # with the real capability in the resolver.
    demo.service_type = None
    demo.system_identifier = None
    demo.steps[2].risk = RiskLevel.RISKY
    return demo
