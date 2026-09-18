from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActionType(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    WAIT = "wait"
    EXTRACT = "extract"
    ASSERT = "assert"


class RiskLevel(StrEnum):
    READ_ONLY = "read_only"
    REVERSIBLE = "reversible"
    RISKY = "risky"
    IRREVERSIBLE = "irreversible"


class RunStatus(StrEnum):
    SUCCESS = "success"
    BUSINESS_OUTCOME = "business_outcome"
    PAUSED = "paused"
    FAILURE = "failure"


class ErrorCategory(StrEnum):
    BUSINESS = "business"
    RECOVERABLE = "recoverable"
    VALIDATION = "validation"
    POLICY = "policy"
    AUTH = "auth"
    TARGET_NOT_FOUND = "target_not_found"
    CHECKPOINT = "checkpoint_failed"
    TIMEOUT = "timeout"
    APPLICATION = "application_error"
    INTERNAL = "internal"


class ServiceType(StrEnum):
    """The client-facing authorization scope AND cross-client reuse key (paired with
    ApplicationBinding.system_identifier — see CapabilityArtifact) for a capability domain.
    Deliberately a closed, admin-curated enum, not client-suppliable free text — a credential's
    `authorized_service_types` only means something if the set of values is fixed in code.

    Only add a member once `ClaudeDiscoveryAgent.discover()` is generalized to derive artifact
    id/inputs/outputs/success-checkpoint from the request instead of its current hardcoded
    lookup-member-savings-balance scenario (see agent/discovery.py) — an enum member with no
    working discovery behind it would silently mislabel whatever discover() actually produces."""

    MEMBER_SAVINGS_BALANCE_LOOKUP = "member_savings_balance_lookup"


class ParameterSpec(BaseModel):
    """One declared input a capability accepts. The full list is what ExecuteV1Request.inputs
    must satisfy -- see CapabilityReviewResponse.inputs."""

    name: str = Field(description="Input key, as used in ExecuteV1Request.inputs and templated "
        "into steps as {{name}}.")
    type: Literal["string", "integer", "number", "boolean"] = Field(
        description="Expected value type. Not currently coerced/validated beyond presence and "
        "`pattern` -- callers should send the right JSON type."
    )
    description: str = Field(description="Human-readable purpose of this input, for a caller or reviewer.")
    required: bool = Field(
        default=True,
        description="When true and the value is missing/empty at execute time, the run fails "
        "before touching the target system with error.category='validation', "
        "error.code='MISSING_INPUT', recoverable=false.",
    )
    sensitive: bool = Field(
        default=False,
        description="Marks the value as PII/secret-like for the Redactor -- never written raw "
        "into evidence or logs.",
    )
    pattern: str | None = Field(
        default=None,
        description="Optional regex the value must fully match. A mismatch fails the run with "
        "error.code='INVALID_INPUT', recoverable=false, before anything touches the target "
        "system.",
    )


class OutputSpec(BaseModel):
    """One declared output a capability produces on success -- the full list describes the shape
    of ExecutionResult.outputs."""

    name: str = Field(description="Output key, matching a Step.output and the key populated in "
        "ExecutionResult.outputs on success.")
    type: Literal["string", "integer", "number", "boolean", "object"] = Field(
        description="Type of the extracted value."
    )
    description: str = Field(description="Human-readable meaning of this output.")
    sensitive: bool = Field(
        default=False,
        description="Marks the value as PII/secret-like for the Redactor -- never written raw "
        "into evidence or logs.",
    )


class Locator(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    strategy: Literal["role", "label", "text", "css", "xpath", "coordinates"] = Field(
        description="How to resolve this element. Preference order at discovery time is "
        "role/label/text (survive markup changes, map to desktop accessibility) over css/xpath, "
        "with coordinates as a last-resort fallback."
    )
    value: str = Field(description="The locator's own value under `strategy` (a role name, CSS "
        "selector, XPath, etc).")
    name: str | None = Field(
        default=None, description="Accessible name to match alongside `strategy='role'`."
    )
    exact: bool = Field(default=True, description="Whether text/label matching must be exact.")
    frame: str | None = Field(
        default=None, description="Frame path, for locators inside a nested iframe."
    )


class Target(BaseModel):
    primary: Locator = Field(description="First locator strategy tried when resolving this element.")
    fallbacks: list[Locator] = Field(
        default_factory=list,
        description="Ordered alternates tried in turn if `primary` fails to resolve.",
    )
    rationale: str = Field(
        description="Why this locator strategy was chosen during discovery -- makes fragility "
        "visible to a reviewer."
    )


class Checkpoint(BaseModel):
    kind: Literal["visible", "hidden", "url", "text", "value"] = Field(
        description="What kind of condition to check (element visible/hidden, current URL, "
        "element text, or element value)."
    )
    target: Target | None = Field(
        default=None, description="Element the checkpoint inspects, when kind requires one."
    )
    expected: str | None = Field(
        default=None, description="Expected value to compare against, when kind requires one."
    )
    timeout_ms: int = Field(
        default=10_000, description="How long to poll for the condition before treating it as failed."
    )


class ErrorRule(BaseModel):
    """A discovery-time declared condition replay watches for at a step, and how to respond if
    it fires -- the mechanism behind RunError/business_code/recoverable on the response side."""

    code: str = Field(description="Stable code surfaced as RunError.code / ExecutionResult.business_code "
        "when this rule fires.")
    category: ErrorCategory = Field(
        description="Surfaced as RunError.category. ErrorCategory.BUSINESS is handled specially "
        "-- it produces RunStatus.BUSINESS_OUTCOME, not a failure."
    )
    when: Checkpoint = Field(description="Condition that, if true, means this rule has fired.")
    message: str = Field(description="Human-readable message surfaced as RunError.message.")
    recovery: Literal["return", "retry", "pause", "fail"] = Field(
        default="return",
        description="'retry': re-check `when` up to max_retries times before falling through to "
        "a hard failure. 'pause': hand off to a human intervention, then re-validate `when` on "
        "resume. 'return'/'fail': hard stop immediately.",
    )
    max_retries: int = Field(
        default=0, description="Retry budget for recovery='retry' before giving up as a hard failure."
    )


class Step(BaseModel):
    id: str = Field(description="Stable step id, referenced by RunError.step_id and tenant overrides.")
    action: ActionType = Field(description="Operation this step performs.")
    description: str = Field(description="Human-readable purpose of this step, for a reviewer.")
    risk: RiskLevel = Field(
        default=RiskLevel.READ_ONLY,
        description="Risk classification (read_only/reversible/risky/irreversible). Policy "
        "requires human approval before a risky/irreversible step executes.",
    )
    target: Target | None = Field(
        default=None, description="Element this step acts on. Required for click/type/select/extract."
    )
    value: str | None = Field(
        default=None,
        description="Literal or {{templated}} value for this step (e.g. text to type, URL to "
        "navigate to). Templates are filled from ExecuteV1Request.inputs.",
    )
    output: str | None = Field(
        default=None,
        description="OutputSpec.name this step's extracted value is written to, for an extract step.",
    )
    checkpoint: Checkpoint | None = Field(
        default=None, description="Condition that must hold after this step for it to count as complete."
    )
    errors: list[ErrorRule] = Field(
        default_factory=list, description="Declared error conditions checked at this step."
    )

    @model_validator(mode="after")
    def validate_step(self) -> Step:
        if (
            self.action
            in {ActionType.CLICK, ActionType.TYPE, ActionType.SELECT, ActionType.EXTRACT}
            and not self.target
        ):
            raise ValueError(f"{self.action} requires a target")
        return self


class ApplicationBinding(BaseModel):
    vendor: str = Field(description="Vendor name of the target application.")
    product: str = Field(description="Product name of the target application.")
    base_url: str = Field(description="Vendor-reference base URL used during discovery.")
    supported_versions: list[str] = Field(
        default_factory=lambda: ["demo-v1"],
        description="Application version variants this artifact is validated against, matched "
        "at replay time via a fingerprint of the live entry screen.",
    )
    tenant_overrides: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-tenant_id patch (e.g. a real base_url, or a step's locator override) "
        "applied on top of the vendor-reference binding at replay time.",
    )


class CapabilityArtifact(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str
    version: int = 1
    name: str
    description: str
    lifecycle: Literal["draft", "validating", "approved", "active", "degraded", "deprecated"] = (
        "draft"
    )
    application: ApplicationBinding
    inputs: list[ParameterSpec]
    outputs: list[OutputSpec]
    steps: list[Step]
    success: Checkpoint
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    discovered_by: str
    approval_required: bool = True
    tags: list[str] = Field(default_factory=list)
    service_type: ServiceType | None = None
    system_identifier: str | None = None

    @property
    def qualified_id(self) -> str:
        return f"{self.id}.v{self.version}"


class RunError(BaseModel):
    """Populated on ExecutionResult only when status == RunStatus.FAILURE. This is the client's
    entire contract for "what went wrong and what do I do now" -- read `message` for a
    human-displayable reason and `recoverable` for the machine-actionable next step."""

    category: ErrorCategory = Field(
        description="Coarse failure bucket (validation, policy, auth, target_not_found, "
        "checkpoint_failed, timeout, application_error, internal, ...). Stable across runs of "
        "the same capability -- safe to branch client-side logic on."
    )
    code: str = Field(
        description="Stable machine-readable error code within the category (e.g. "
        "'MISSING_INPUT', 'APPROVAL_DENIED', 'TARGET_NOT_FOUND'). Use this, not `message`, for "
        "programmatic handling -- `message` wording may change."
    )
    message: str = Field(
        description="Human-readable explanation of the failure. Safe to show directly to an "
        "operator; never contains secrets or raw PII (see Redactor)."
    )
    step_id: str | None = Field(
        default=None,
        description="Artifact Step.id where the failure occurred, when the failure happened "
        "mid-replay (None for pre-flight failures such as input validation).",
    )
    expected: str | None = Field(
        default=None, description="What the failing checkpoint/rule expected to observe, if known."
    )
    observed: str | None = Field(
        default=None, description="What was actually observed instead, if known."
    )
    evidence_path: str | None = Field(
        default=None,
        description="Path to the redacted screenshot/evidence captured at failure time, for "
        "human review -- not a public URL, resolved against the evidence store.",
    )
    recoverable: bool = Field(
        default=False,
        description="True: the client may safely resubmit the identical request as-is (e.g. a "
        "transient ACTION_TIMEOUT) -- automatic requeue is reasonable. False (the default): "
        "resubmitting the same request will very likely fail the same way -- a human must review "
        "the failure (bad input, denied policy/approval, broken locator, ambiguous app state) "
        "before the request is requeued.",
    )


class ExecutionResult(BaseModel):
    """Response body for POST /v1/capabilities/{id}/execute. `status` tells the client which of
    the four terminal states the run reached; `error` is the client's signal that the run failed
    and needs attention (see RunError.recoverable for whether it's safe to requeue immediately or
    needs review first)."""

    run_id: str = Field(description="Unique id for this execution run, for evidence lookup and support.")
    status: RunStatus = Field(
        description="Terminal run state: 'success' (outputs populated), 'business_outcome' (a "
        "known domain result such as MEMBER_NOT_FOUND, see business_code), 'paused' (awaiting "
        "human intervention, see intervention_id), or 'failure' (hard stop, see error). Only "
        "'failure' means something needs review before this request is requeued."
    )
    capability_id: str | None = Field(
        default=None, description="Qualified id (id.vN) of the artifact that was replayed."
    )
    outputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Typed outputs extracted per the artifact's OutputSpec list. Populated only "
        "on status == 'success'.",
    )
    business_code: str | None = Field(
        default=None,
        description="Stable domain outcome code (e.g. 'MEMBER_NOT_FOUND') when "
        "status == 'business_outcome' -- not an error, a legitimate answer the artifact declared.",
    )
    error: RunError | None = Field(
        default=None,
        description="Structured failure detail, populated only when status == 'failure'. This is "
        "the field a client checks to know the request failed and must be reviewed (and, once "
        "review clears it or error.recoverable is true, requeued).",
    )
    intervention_id: str | None = Field(
        default=None,
        description="Id of the pending human intervention when status == 'paused' -- resume via "
        "the intervention API once a human has acted.",
    )
    started_at: datetime = Field(description="UTC timestamp the run began.")
    completed_at: datetime | None = Field(
        default=None,
        description="UTC timestamp the run reached a terminal state. None while still in "
        "progress (not observable through this synchronous response today).",
    )


class CapabilityDescriptor(BaseModel):
    id: str
    name: str
    description: str
    source: Literal["local_tool", "mcp_tool", "skill", "computer_use", "api"]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk: RiskLevel
    trust: Literal["discovered", "verified", "approved", "restricted", "blocked"] = "approved"
    reliability: float = 1.0
    tags: list[str] = Field(default_factory=list)
    service_type: ServiceType | None = Field(
        default=None,
        description="Authorization scope this capability requires, when known (e.g. carried "
        "over from a computer_use artifact's own service_type). None means no service_type "
        "scoping applies to this capability -- an authenticated caller may invoke it regardless "
        "of authorized_service_types.",
    )
