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
    POLICY = "policy"
    AUTH = "auth"
    TARGET_NOT_FOUND = "target_not_found"
    CHECKPOINT = "checkpoint_failed"
    TIMEOUT = "timeout"
    APPLICATION = "application_error"
    INTERNAL = "internal"


class ParameterSpec(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean"]
    description: str
    required: bool = True
    sensitive: bool = False
    pattern: str | None = None


class OutputSpec(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean", "object"]
    description: str
    sensitive: bool = False


class Locator(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    strategy: Literal["role", "label", "text", "css", "xpath", "coordinates"]
    value: str
    name: str | None = None
    exact: bool = True
    frame: str | None = None


class Target(BaseModel):
    primary: Locator
    fallbacks: list[Locator] = Field(default_factory=list)
    rationale: str


class Checkpoint(BaseModel):
    kind: Literal["visible", "hidden", "url", "text", "value"]
    target: Target | None = None
    expected: str | None = None
    timeout_ms: int = 10_000


class ErrorRule(BaseModel):
    code: str
    category: ErrorCategory
    when: Checkpoint
    message: str
    recovery: Literal["return", "retry", "pause", "fail"] = "return"
    max_retries: int = 0


class Step(BaseModel):
    id: str
    action: ActionType
    description: str
    risk: RiskLevel = RiskLevel.READ_ONLY
    target: Target | None = None
    value: str | None = None
    output: str | None = None
    checkpoint: Checkpoint | None = None
    errors: list[ErrorRule] = Field(default_factory=list)

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
    vendor: str
    product: str
    base_url: str
    supported_versions: list[str] = Field(default_factory=lambda: ["demo-v1"])
    tenant_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)


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

    @property
    def qualified_id(self) -> str:
        return f"{self.id}.v{self.version}"


class RunError(BaseModel):
    category: ErrorCategory
    code: str
    message: str
    step_id: str | None = None
    expected: str | None = None
    observed: str | None = None
    evidence_path: str | None = None
    recoverable: bool = False


class ExecutionResult(BaseModel):
    run_id: str
    status: RunStatus
    capability_id: str | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)
    business_code: str | None = None
    error: RunError | None = None
    intervention_id: str | None = None
    started_at: datetime
    completed_at: datetime | None = None


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
