import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from capability_platform.computer_use.surface import (
    PlaywrightSurface,
    SurfaceAdapter,
    SurfaceTimeout,
)
from capability_platform.intervention.manager import interventions
from capability_platform.models import (
    ActionType,
    CapabilityArtifact,
    Checkpoint,
    ErrorCategory,
    ExecutionResult,
    RunError,
    RunStatus,
    Step,
)
from capability_platform.observability.evidence import EvidenceCollector
from capability_platform.policy.engine import PolicyEngine, PolicyViolation


class ReplayEngine:
    """Executes artifact steps exactly as declared. This module has no LLM dependency."""

    def __init__(
        self,
        policy: PolicyEngine,
        evidence_root,
        headless: bool = False,
        surface_factory: Callable[[bool], SurfaceAdapter] = PlaywrightSurface,
    ) -> None:
        self.policy = policy
        self.evidence_root = evidence_root
        self.headless = headless
        # Defaults to the concrete Playwright driver but takes any SurfaceAdapter — this is the
        # seam a desktop/legacy-web adapter would plug into without changing this class at all.
        self.surface_factory = surface_factory

    @staticmethod
    def _render(value: str | None, inputs: dict[str, Any]) -> str:
        if value is None:
            return ""
        return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda match: str(inputs[match.group(1)]), value)

    async def _checkpoint(
        self, surface: SurfaceAdapter, checkpoint: Checkpoint, inputs: dict[str, Any]
    ) -> bool:
        expected = self._render(checkpoint.expected, inputs)
        if checkpoint.kind == "url":
            return expected in await surface.current_url()
        if checkpoint.kind == "visible":
            return bool(checkpoint.target and await surface.visible(checkpoint.target))
        if checkpoint.kind == "hidden":
            return bool(checkpoint.target and not await surface.visible(checkpoint.target))
        if checkpoint.kind == "text":
            return bool(checkpoint.target and expected in await surface.extract(checkpoint.target))
        if checkpoint.kind == "value":
            value = await surface.value_of(checkpoint.target) if checkpoint.target else None
            return value == expected
        return False

    async def _check_errors(self, surface: SurfaceAdapter, step: Step, inputs: dict[str, Any]):
        for rule in step.errors:
            if await self._checkpoint(surface, rule.when, inputs):
                return rule
        return None

    async def _request_approval(
        self,
        evidence: EvidenceCollector,
        run_id: str,
        artifact: CapabilityArtifact,
        step: Step,
        surface: SurfaceAdapter,
        result: ExecutionResult,
    ) -> bool:
        """Pause on the same live session for human approval of a risky/irreversible step,
        reusing the same intervention mechanism as an unexpected-condition handoff."""
        screenshot = await evidence.screenshot(await surface.screenshot(), f"approval-{step.id}")
        paused_state = await surface.observe()
        reason = f"Step {step.id!r} is {step.risk} and requires human approval before it runs"
        item = interventions.create(
            run_id,
            reason,
            capability_id=artifact.qualified_id,
            step_id=step.id,
            screenshot=screenshot,
            state=paused_state,
            page=surface.page,
        )
        result.intervention_id = item.id
        evidence.event(
            "intervention.created",
            intervention_id=item.id,
            run_id=run_id,
            capability_id=artifact.qualified_id,
            step_id=step.id,
            reason=reason,
            screenshot=screenshot,
            state=paused_state,
        )
        evidence.event("control.transferred", owner="human", intervention_id=item.id)
        result.status = RunStatus.PAUSED
        approved = await interventions.wait_for_approval(item.id)
        result.status = RunStatus.FAILURE
        evidence.event(
            "control.transferred", owner="automation", intervention_id=item.id, approved=approved
        )
        return approved

    @staticmethod
    def _validate_inputs(
        artifact: CapabilityArtifact, inputs: dict[str, Any]
    ) -> RunError | None:
        """Check inputs against the artifact's typed contract before touching a browser."""
        for spec in artifact.inputs:
            value = inputs.get(spec.name)
            if spec.required and (value is None or value == ""):
                return RunError(
                    category=ErrorCategory.VALIDATION,
                    code="MISSING_INPUT",
                    message=f"Missing required input '{spec.name}'",
                )
            if value is not None and spec.pattern and not re.fullmatch(spec.pattern, str(value)):
                return RunError(
                    category=ErrorCategory.VALIDATION,
                    code="INVALID_INPUT",
                    message=f"Input '{spec.name}' does not match required pattern {spec.pattern!r}",
                )
        return None

    async def execute(
        self, artifact: CapabilityArtifact, inputs: dict[str, Any]
    ) -> ExecutionResult:
        run_id = str(uuid4())
        started = datetime.now(UTC)
        evidence = EvidenceCollector(self.evidence_root, run_id)
        result = ExecutionResult(
            run_id=run_id,
            status=RunStatus.FAILURE,
            capability_id=artifact.qualified_id,
            started_at=started,
        )
        validation_error = self._validate_inputs(artifact, inputs)
        if validation_error:
            result.error = validation_error
            result.completed_at = datetime.now(UTC)
            evidence.event("validation.failed", error=validation_error.model_dump(mode="json"))
            return result
        surface = self.surface_factory(self.headless)
        try:
            self.policy.authorize_url(artifact.application.base_url)
            await surface.start(artifact.application.base_url)
            evidence.event("replay.started", capability=artifact.qualified_id, inputs=inputs)
            for step in artifact.steps:
                evidence.event("step.started", step_id=step.id, action=step.action)
                approved_for_step = False
                if self.policy.requires_approval(step):
                    approved_for_step = await self._request_approval(
                        evidence, run_id, artifact, step, surface, result
                    )
                    if not approved_for_step:
                        denial_screenshot = await evidence.screenshot(
                            await surface.screenshot(), f"denied-{step.id}"
                        )
                        result.error = RunError(
                            category=ErrorCategory.POLICY,
                            code="APPROVAL_DENIED",
                            message=f"Step {step.id} ({step.risk}) was denied by human review",
                            step_id=step.id,
                            evidence_path=denial_screenshot,
                        )
                        result.completed_at = datetime.now(UTC)
                        # Let the enclosing try's `finally` emit replay.finished and close the
                        # surface, same as the BUSINESS_OUTCOME early-return path below does —
                        # doing it here too would double-close and double-log.
                        return result
                try:
                    self.policy.authorize_step(step, approved=approved_for_step)
                    error_rule = await self._check_errors(surface, step, inputs)
                    if error_rule and error_rule.category == ErrorCategory.BUSINESS:
                        result.status = RunStatus.BUSINESS_OUTCOME
                        result.business_code = error_rule.code
                        result.completed_at = datetime.now(UTC)
                        evidence.event("business_outcome", code=error_rule.code, step_id=step.id)
                        return result
                    if step.action == ActionType.NAVIGATE:
                        url = self._render(step.value, inputs)
                        self.policy.authorize_url(url)
                        await surface.navigate(url)
                    elif step.action == ActionType.CLICK:
                        await surface.click(step.target)
                    elif step.action == ActionType.TYPE:
                        await surface.type(step.target, self._render(step.value, inputs))
                    elif step.action == ActionType.WAIT:
                        await surface.wait(int(step.value or "500"))
                    elif step.action == ActionType.EXTRACT:
                        raw = await surface.extract(step.target)
                        result.outputs[step.output or step.id] = (
                            float(raw.replace("$", "").replace(",", "")) if "$" in raw else raw
                        )
                    elif step.action == ActionType.ASSERT and step.checkpoint:
                        if not await self._checkpoint(surface, step.checkpoint, inputs):
                            raise AssertionError("assertion failed")

                    error_rule = await self._check_errors(surface, step, inputs)
                    if error_rule:
                        if error_rule.category == ErrorCategory.BUSINESS:
                            result.status = RunStatus.BUSINESS_OUTCOME
                            result.business_code = error_rule.code
                            result.completed_at = datetime.now(UTC)
                            evidence.event(
                                "business_outcome", code=error_rule.code, step_id=step.id
                            )
                            return result
                        if error_rule.recovery == "retry":
                            resolved = False
                            for attempt in range(error_rule.max_retries):
                                await surface.wait(500)
                                evidence.event(
                                    "recoverable.retry",
                                    code=error_rule.code,
                                    step_id=step.id,
                                    attempt=attempt + 1,
                                    max_retries=error_rule.max_retries,
                                )
                                if not await self._checkpoint(surface, error_rule.when, inputs):
                                    resolved = True
                                    break
                            if not resolved:
                                raise RuntimeError(
                                    f"Recoverable condition {error_rule.code!r} at step "
                                    f"{step.id!r} did not clear after "
                                    f"{error_rule.max_retries} retries"
                                )
                            evidence.event(
                                "recoverable.resolved", code=error_rule.code, step_id=step.id
                            )
                            continue
                        if error_rule.recovery == "pause":
                            screenshot = await evidence.screenshot(await surface.screenshot(), f"pause-{step.id}")
                            paused_state = await surface.observe()
                            item = interventions.create(
                                run_id,
                                error_rule.message,
                                capability_id=artifact.qualified_id,
                                step_id=step.id,
                                screenshot=screenshot,
                                state=paused_state,
                                page=surface.page,
                            )
                            result.intervention_id = item.id
                            evidence.event(
                                "intervention.created",
                                intervention_id=item.id,
                                run_id=run_id,
                                capability_id=artifact.qualified_id,
                                step_id=step.id,
                                reason=error_rule.message,
                                screenshot=screenshot,
                                state=paused_state,
                            )
                            evidence.event(
                                "control.transferred", owner="human", intervention_id=item.id
                            )
                            result.status = RunStatus.PAUSED
                            await interventions.wait_for_resume(item.id)
                            result.status = RunStatus.FAILURE  # in-progress sentinel again
                            evidence.event(
                                "control.transferred",
                                owner="automation",
                                intervention_id=item.id,
                            )
                            resumed_state = await surface.observe()
                            evidence.event("resume.observed", state=resumed_state)
                            if await self._checkpoint(surface, error_rule.when, inputs):
                                raise RuntimeError(
                                    f"Interruption at step {step.id!r} was not resolved "
                                    "before resume — the condition is still present"
                                )
                            evidence.event("resume.validated", step_id=step.id)
                            continue
                        # A declared rule that isn't business/retry/pause is a deliberate hard
                        # stop — preserve its own category/code (e.g. auth, target_not_found)
                        # instead of collapsing to the generic checkpoint bucket below.
                        declared_screenshot = await evidence.screenshot(
                            await surface.screenshot(), f"failure-{step.id}"
                        )
                        raise StepFailure(
                            step.id,
                            error_rule.message,
                            declared_screenshot,
                            category=error_rule.category,
                            code=error_rule.code,
                        )
                    if step.checkpoint and not await self._checkpoint(
                        surface, step.checkpoint, inputs
                    ):
                        raise AssertionError("step checkpoint failed")
                    evidence.event("step.completed", step_id=step.id)

                except PolicyViolation:
                    raise
                except StepFailure:
                    raise
                except SurfaceTimeout as exc:
                    screenshot = await evidence.screenshot(await surface.screenshot(), f"failure-{step.id}")
                    raise StepFailure(
                        step.id, str(exc), screenshot,
                        category=ErrorCategory.TIMEOUT, code="ACTION_TIMEOUT",
                    ) from exc
                except LookupError as exc:
                    screenshot = await evidence.screenshot(await surface.screenshot(), f"failure-{step.id}")
                    raise StepFailure(
                        step.id, str(exc), screenshot,
                        category=ErrorCategory.TARGET_NOT_FOUND, code="TARGET_NOT_FOUND",
                    ) from exc
                except Exception as exc:
                    screenshot = await evidence.screenshot(await surface.screenshot(), f"failure-{step.id}")
                    raise StepFailure(step.id, str(exc), screenshot) from exc

            if not await self._checkpoint(surface, artifact.success, inputs):
                raise StepFailure(
                    "success",
                    "final checkpoint failed",
                    await evidence.screenshot(await surface.screenshot(), "failure-final"),
                )
            result.status = RunStatus.SUCCESS
            result.completed_at = datetime.now(UTC)
            evidence.event("replay.completed", outputs=result.outputs)
            return result
        except PolicyViolation as exc:
            result.error = RunError(
                category=ErrorCategory.POLICY, code="POLICY_DENIED", message=str(exc)
            )
        except StepFailure as exc:
            result.error = RunError(
                category=exc.category,
                code=exc.code,
                message=exc.message,
                step_id=exc.step_id,
                evidence_path=exc.screenshot,
            )
        except Exception as exc:  # noqa: BLE001 - convert unexpected driver errors to result contract
            result.error = RunError(
                category=ErrorCategory.INTERNAL, code="UNEXPECTED", message=str(exc)
            )
        finally:
            result.completed_at = result.completed_at or datetime.now(UTC)
            evidence.event("replay.finished", result=result.model_dump(mode="json"))
            await surface.close()
        return result


class StepFailure(RuntimeError):
    def __init__(
        self,
        step_id: str,
        message: str,
        screenshot: str | None,
        category: ErrorCategory = ErrorCategory.CHECKPOINT,
        code: str = "REPLAY_STEP_FAILED",
    ) -> None:
        self.step_id = step_id
        self.message = message
        self.screenshot = screenshot
        self.category = category
        self.code = code
        super().__init__(message)
