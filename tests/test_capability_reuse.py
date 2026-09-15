"""CapabilityArtifact.service_type/system_identifier are optional, backward-compatible fields,
and ArtifactStore.find_approved_by_service_and_system() is the cross-client reuse lookup they
enable (T: production auth/reuse layer). No live browser needed."""

from pathlib import Path

from capability_platform.capabilities.store import ArtifactStore
from capability_platform.models import (
    ApplicationBinding,
    CapabilityArtifact,
    Checkpoint,
    Locator,
    OutputSpec,
    ParameterSpec,
    ServiceType,
    Target,
)


def _artifact(
    id_: str,
    lifecycle: str,
    service_type: ServiceType | None = None,
    system_identifier: str | None = None,
) -> CapabilityArtifact:
    return CapabilityArtifact(
        id=id_,
        name="Test capability",
        description="test",
        lifecycle=lifecycle,
        application=ApplicationBinding(vendor="x", product="y", base_url="http://127.0.0.1:8001"),
        inputs=[ParameterSpec(name="memberId", type="string", description="x")],
        outputs=[OutputSpec(name="out", type="string", description="x")],
        steps=[],
        success=Checkpoint(
            kind="visible",
            target=Target(primary=Locator(strategy="text", value="x"), rationale="x"),
        ),
        discovered_by="test",
        service_type=service_type,
        system_identifier=system_identifier,
    )


def test_capability_artifact_constructs_without_service_type_or_system_identifier():
    """Backward compatibility: the one real on-disk artifact predates these fields."""
    artifact = _artifact("legacy-cap", "approved")
    assert artifact.service_type is None
    assert artifact.system_identifier is None


def test_real_artifact_on_disk_has_no_service_type_yet():
    artifact = ArtifactStore(Path("artifacts")).load("lookup-member-savings-balance.v1")
    assert artifact.service_type is None
    assert artifact.system_identifier is None


def test_find_approved_by_service_and_system_matches(tmp_path):
    store = ArtifactStore(tmp_path)
    store.save(
        _artifact(
            "balance-cap",
            "approved",
            service_type=ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP,
            system_identifier="legacy-member-servicing-demo",
        )
    )

    found = store.find_approved_by_service_and_system(
        ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP, "legacy-member-servicing-demo"
    )
    assert found is not None
    assert found.id == "balance-cap"


def test_find_approved_by_service_and_system_returns_none_on_mismatch(tmp_path):
    store = ArtifactStore(tmp_path)
    store.save(
        _artifact(
            "balance-cap",
            "approved",
            service_type=ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP,
            system_identifier="legacy-member-servicing-demo",
        )
    )

    assert (
        store.find_approved_by_service_and_system(
            ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP, "some-other-system"
        )
        is None
    )


def test_find_approved_by_service_and_system_ignores_draft_lifecycle(tmp_path):
    store = ArtifactStore(tmp_path)
    store.save(
        _artifact(
            "balance-cap",
            "draft",
            service_type=ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP,
            system_identifier="legacy-member-servicing-demo",
        )
    )

    assert (
        store.find_approved_by_service_and_system(
            ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP, "legacy-member-servicing-demo"
        )
        is None
    )
