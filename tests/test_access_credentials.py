from capability_platform.access.credentials import (
    JSONCredentialStore,
    hash_password,
    verify_password,
)
from capability_platform.access.models import ClientCredential
from capability_platform.models import ServiceType


def test_hash_and_verify_password_roundtrip():
    password_hash, password_salt = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", password_hash, password_salt)


def test_verify_password_rejects_wrong_password():
    password_hash, password_salt = hash_password("correct-horse-battery-staple")
    assert not verify_password("wrong-password", password_hash, password_salt)


def test_hash_password_uses_a_random_salt_per_call():
    hash_a, salt_a = hash_password("same-password")
    hash_b, salt_b = hash_password("same-password")
    assert salt_a != salt_b
    assert hash_a != hash_b


def test_json_credential_store_get_returns_none_for_unknown_client(tmp_path):
    store = JSONCredentialStore(tmp_path)
    assert store.get("nobody") is None


def test_json_credential_store_save_get_roundtrip(tmp_path):
    store = JSONCredentialStore(tmp_path)
    password_hash, password_salt = hash_password("secret123")
    credential = ClientCredential(
        client_id="demo-client",
        password_hash=password_hash,
        password_salt=password_salt,
        authorized_service_types=[ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP],
        is_admin=True,
    )
    store.save(credential)

    loaded = store.get("demo-client")
    assert loaded is not None
    assert loaded.client_id == "demo-client"
    assert loaded.is_admin is True
    assert loaded.authorized_service_types == [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP]
    assert verify_password("secret123", loaded.password_hash, loaded.password_salt)


def test_authorize_checks_service_type_membership(tmp_path):
    store = JSONCredentialStore(tmp_path)
    password_hash, password_salt = hash_password("secret123")
    credential = ClientCredential(
        client_id="demo-client",
        password_hash=password_hash,
        password_salt=password_salt,
        authorized_service_types=[ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP],
    )
    assert store.authorize(credential, ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP) is True
