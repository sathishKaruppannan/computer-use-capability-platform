"""Gate: the real, committed evidence/ directory must contain no unredacted secrets, API keys,
authorization headers, cookies, or SSNs. Runs against actual committed evidence, not a fixture —
deliberately checks real state rather than synthetic data."""

from pathlib import Path

from scripts.validate_evidence import scan


def test_committed_evidence_has_no_unredacted_secrets():
    problems = scan(Path("evidence"))
    assert not problems, "unredacted sensitive data found in evidence/:\n" + "\n".join(problems)
