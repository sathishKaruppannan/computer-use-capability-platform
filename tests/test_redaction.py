from capability_platform.observability.evidence import Redactor


def test_redacts_sensitive_values():
    cleaned = Redactor.clean({"ssn": "123-45-6789", "authorization": "Bearer-secret"})
    rendered = str(cleaned)
    assert "123-45-6789" not in rendered
    assert "Bearer-secret" not in rendered


def test_redacts_api_key():
    cleaned = Redactor.clean({"api_key": "sk-ant-abcdefghijklmnopqrstuvwxyz"})
    rendered = str(cleaned)
    assert "sk-ant-abcdefghijklmnopqrstuvwxyz" not in rendered
    assert "[REDACTED_SECRET]" in rendered


def test_redacts_cookie_and_session_id():
    cleaned = Redactor.clean({"cookie": "sessionid=deadbeef123", "session_id": "abc-123-xyz"})
    rendered = str(cleaned)
    assert "sessionid=deadbeef123" not in rendered
    assert "abc-123-xyz" not in rendered
    assert "[REDACTED_COOKIE]" in rendered
    assert "[REDACTED_SESSION]" in rendered
