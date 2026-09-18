"""Layer 3.5: PlanStep -> CapabilityResolution. Queries the registry, checks input/output/trust/
policy/tenant compatibility, ranks usable candidates, and falls back to COMPUTER_USE_DISCOVERY
(or UNRESOLVED) only when nothing approved and deterministic fits."""

from __future__ import annotations

from typing import Any

from capability_platform.access.tenant_credentials import CREDENTIAL_FIELD_NAMES
from capability_platform.agent.models import (
    CapabilityCandidate,
    CapabilityResolution,
    PlanStep,
    ResolutionType,
)
from capability_platform.capabilities import ranking
from capability_platform.capabilities.registry import CapabilityRegistry
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.models import CapabilityDescriptor, RiskLevel
from capability_platform.policy.engine import PolicyEngine, PolicyViolation

_RESOLUTION_TYPE_BY_SOURCE: dict[str, ResolutionType] = {
    "api": ResolutionType.API,
    "local_tool": ResolutionType.LOCAL_TOOL,
    "mcp_tool": ResolutionType.MCP_TOOL,
    "skill": ResolutionType.SKILL,
    "computer_use": ResolutionType.COMPUTER_USE_CAPABILITY,
}


class CapabilityResolver:
    def __init__(
        self, registry: CapabilityRegistry, artifact_store: ArtifactStore, policy: PolicyEngine
    ) -> None:
        self.registry = registry
        self.artifact_store = artifact_store
        self.policy = policy

    def resolve(self, step: PlanStep, context: dict[str, Any] | None = None) -> CapabilityResolution:
        context = context or {}
        query = " ".join([step.description, *step.required_inputs, *step.produced_outputs])
        scored = [
            self._evaluate(descriptor, semantic_score, step, context)
            for descriptor, semantic_score in self.registry.search(query, limit=10)
        ]

        usable = [candidate for candidate in scored if self._is_usable(candidate)]
        if usable:
            # Tie-break (or near-tie) toward fewer stored-credential dependencies: a capability
            # that doesn't need a per-client login is preferable to one that does, all else
            # equal, since it works immediately rather than needing an admin to have already
            # saved credentials for the calling client. Primary sort is still final_score.
            selected = max(
                usable,
                key=lambda candidate: (
                    candidate.final_score,
                    -self._credential_field_count(candidate.descriptor),
                ),
            )
            alternatives = [candidate for candidate in scored if candidate is not selected]
            return CapabilityResolution(
                step_id=step.id,
                resolution_type=_RESOLUTION_TYPE_BY_SOURCE[selected.descriptor.source],
                selected=selected,
                alternatives=alternatives,
                reason=(
                    f"Selected '{selected.descriptor.id}' (source={selected.descriptor.source}, "
                    f"score={selected.final_score:.3f})"
                ),
            )

        if context.get("allow_discovery", True):
            return CapabilityResolution(
                step_id=step.id,
                resolution_type=ResolutionType.COMPUTER_USE_DISCOVERY,
                alternatives=scored,
                reason="No approved deterministic capability matched this step; falling back to computer-use discovery.",
                discovery_goal=step.description,
            )
        return CapabilityResolution(
            step_id=step.id,
            resolution_type=ResolutionType.UNRESOLVED,
            alternatives=scored,
            reason="No approved deterministic capability matched this step and discovery is disabled for this context.",
        )

    def _evaluate(
        self,
        descriptor: CapabilityDescriptor,
        semantic_score: float,
        step: PlanStep,
        context: dict[str, Any],
    ) -> CapabilityCandidate:
        # Direction matters: a capability is input-compatible only if EVERY input IT requires is
        # something the step actually supplies -- not merely that the step's inputs are among
        # the ones it happens to accept. Otherwise a capability needing extra, unsupplied inputs
        # (e.g. a login-gated variant needing username/password the step never declared) would
        # look compatible and only fail once actually executed.
        descriptor_required_inputs = {
            name
            for name, spec in descriptor.input_schema.items()
            if not isinstance(spec, dict) or spec.get("required", True)
        }
        # Sensitive (credential-shaped) inputs are satisfiable via the per-client
        # TenantCredentialStore at execution time, not something the plan step needs to declare
        # in advance -- a step asking for "the savings balance" shouldn't need to know ahead of
        # time that one candidate capability happens to sit behind a login. The executor is what
        # actually resolves them (and fails cleanly, asking an admin to add credentials, if none
        # are stored for the calling client).
        credential_fields = self._credential_fields(descriptor)
        input_compatible = descriptor_required_inputs.issubset(set(step.required_inputs) | credential_fields)
        output_compatible = all(name in descriptor.output_schema for name in step.produced_outputs)
        # Re-checked here even though CapabilityRegistry.search() already excludes
        # blocked/discovered candidates -- defense in depth for callers that hand the resolver a
        # candidate list built some other way (e.g. unit tests).
        trust_ok = descriptor.trust == "approved"
        policy_ok = self._policy_ok(descriptor)
        tenant_ok = self._tenant_ok(descriptor, context)
        final_score = ranking.score(descriptor, semantic_score)

        reasons = []
        if not input_compatible:
            reasons.append("input schema does not satisfy this step's required inputs")
        if not output_compatible:
            reasons.append("output schema does not satisfy this step's produced outputs")
        if not trust_ok:
            reasons.append(f"capability trust state is '{descriptor.trust}', not 'approved'")
        if not policy_ok:
            reasons.append("blocked by policy")
        if not tenant_ok:
            reasons.append("not applicable to the requesting tenant")

        return CapabilityCandidate(
            descriptor=descriptor,
            semantic_score=semantic_score,
            input_compatible=input_compatible,
            output_compatible=output_compatible,
            trust_ok=trust_ok,
            policy_ok=policy_ok,
            tenant_ok=tenant_ok,
            reliability=descriptor.reliability,
            final_score=final_score,
            rejection_reasons=reasons,
        )

    def _policy_ok(self, descriptor: CapabilityDescriptor) -> bool:
        if descriptor.source == "computer_use":
            try:
                artifact = self.artifact_store.load(descriptor.id)
            except FileNotFoundError:
                return False
            try:
                self.policy.authorize_url(artifact.application.base_url)
            except PolicyViolation:
                return False
            return True
        # Conservative default for non-computer_use sources with no executor-level policy check
        # of their own yet: only an irreversible action is blocked outright at resolution time.
        return descriptor.risk != RiskLevel.IRREVERSIBLE

    @staticmethod
    def _tenant_ok(descriptor: CapabilityDescriptor, context: dict[str, Any]) -> bool:
        tenant_id = context.get("tenant_id")
        if not tenant_id:
            return True
        tenant_tags = [tag for tag in descriptor.tags if tag.startswith("tenant:")]
        if not tenant_tags:
            return True
        return f"tenant:{tenant_id}" in tenant_tags

    @staticmethod
    def _credential_fields(descriptor: CapabilityDescriptor) -> set[str]:
        return set(descriptor.input_schema) & CREDENTIAL_FIELD_NAMES

    @classmethod
    def _credential_field_count(cls, descriptor: CapabilityDescriptor) -> int:
        return len(cls._credential_fields(descriptor))

    @staticmethod
    def _is_usable(candidate: CapabilityCandidate) -> bool:
        return (
            candidate.input_compatible
            and candidate.output_compatible
            and candidate.trust_ok
            and candidate.policy_ok
            and candidate.tenant_ok
        )
