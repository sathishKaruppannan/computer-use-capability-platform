from pathlib import Path

from capability_platform.access.models import TenantCredential
from capability_platform.access.tenant_credentials import (
    CREDENTIAL_FIELD_NAMES,
    JSONTenantCredentialStore,
)


def test_credential_field_names_is_username_and_password_only():
    assert CREDENTIAL_FIELD_NAMES == frozenset({"username", "password"})


def test_get_returns_none_when_nothing_stored(tmp_path: Path):
    store = JSONTenantCredentialStore(tmp_path / "tenant_credentials")
    assert store.get("some-capability.v1", "demo-client") is None


def test_save_then_get_round_trips(tmp_path: Path):
    store = JSONTenantCredentialStore(tmp_path / "tenant_credentials")
    store.save(
        TenantCredential(
            capability_id="secure-cap.v1", client_id="demo-client", username="demo", password="letmein-2024"
        )
    )
    stored = store.get("secure-cap.v1", "demo-client")
    assert stored is not None
    assert stored.username == "demo"
    assert stored.password == "letmein-2024"


def test_same_capability_different_clients_are_stored_independently(tmp_path: Path):
    store = JSONTenantCredentialStore(tmp_path / "tenant_credentials")
    store.save(
        TenantCredential(capability_id="secure-cap.v1", client_id="client-a", username="a", password="a-pw")
    )
    store.save(
        TenantCredential(capability_id="secure-cap.v1", client_id="client-b", username="b", password="b-pw")
    )
    assert store.get("secure-cap.v1", "client-a").username == "a"
    assert store.get("secure-cap.v1", "client-b").username == "b"


def test_saving_again_for_the_same_pair_overwrites_the_previous_value(tmp_path: Path):
    store = JSONTenantCredentialStore(tmp_path / "tenant_credentials")
    store.save(
        TenantCredential(capability_id="secure-cap.v1", client_id="demo-client", username="old", password="old-pw")
    )
    store.save(
        TenantCredential(capability_id="secure-cap.v1", client_id="demo-client", username="new", password="new-pw")
    )
    stored = store.get("secure-cap.v1", "demo-client")
    assert stored.username == "new"
    assert stored.password == "new-pw"
