from dataclasses import dataclass
from typing import ClassVar
from urllib.parse import urlparse

from capability_platform.models import ActionType, RiskLevel, Step


class PolicyViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class Policy:
    allowed_hosts: frozenset[str]
    allowed_actions: frozenset[ActionType]
    max_risk_without_approval: RiskLevel = RiskLevel.REVERSIBLE


class PolicyEngine:
    _risk_order: ClassVar[dict[RiskLevel, int]] = {
        RiskLevel.READ_ONLY: 0,
        RiskLevel.REVERSIBLE: 1,
        RiskLevel.RISKY: 2,
        RiskLevel.IRREVERSIBLE: 3,
    }

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    def authorize_url(self, url: str) -> None:
        host = urlparse(url).hostname
        if host not in self.policy.allowed_hosts:
            raise PolicyViolation(f"Host is not allowlisted: {host}")

    def authorize_step(self, step: Step, approved: bool = False) -> None:
        if step.action not in self.policy.allowed_actions:
            raise PolicyViolation(f"Action is not allowlisted: {step.action}")
        maximum = self._risk_order[self.policy.max_risk_without_approval]
        if self._risk_order[step.risk] > maximum and not approved:
            raise PolicyViolation(f"Step {step.id} requires human approval ({step.risk})")


def default_policy() -> Policy:
    return Policy(
        allowed_hosts=frozenset({"127.0.0.1", "localhost", "demo-app"}),
        allowed_actions=frozenset(ActionType),
    )
