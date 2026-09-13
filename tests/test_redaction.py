from capability_platform.observability.evidence import Redactor


def test_redacts_sensitive_values():
    cleaned = Redactor.clean({"ssn": "123-45-6789", "authorization": "Bearer-secret"})
    rendered = str(cleaned)
    assert "123-45-6789" not in rendered
    assert "Bearer-secret" not in rendered
