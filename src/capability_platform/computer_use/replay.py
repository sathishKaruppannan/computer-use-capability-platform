import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from capability_platform.computer_use.surface import PlaywrightSurface
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

    def __init__(self, policy: PolicyEngine, evidence_root, headless: bool = False) -> None:
        self.policy = policy
        self.evidence_root = evidence_root
        self.headless = headless

    @staticmethod
    def _render(value: str | None, inputs: dict[str, Any]) -> str:
        if value is None:
            return ""
        return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda match: str(inputs[match.group(1)]), value)

    async def _checkpoint(
        self, surface: PlaywrightSurface, checkpoint: Checkpoint, inputs: dict[str, Any]
    ) -> bool:
        assert surface.page
        expected = self._render(checkpoint.expected, inputs)
        if checkpoint.kind == "url":
            return expected in surface.page.url
        if checkpoint.kind == "visible":
            return bool(checkpoint.target and await surface.visible(checkpoint.target))
        if checkpoint.kind == "hidden":
            return bool(checkpoint.target and not await surface.visible(checkpoint.target))
        if checkpoint.kind == "text":
            return bool(checkpoint.target and expected in await surface.extract(checkpoint.target))
        if checkpoint.kind == "value":
            element = await surface.resolve(checkpoint.target) if checkpoint.target else None
            return bool(element and await element.input_value() == expected)
        return False

    async def _check_errors(self, surface: PlaywrightSurface, step: Step, inputs: dict[str, Any]):
        for rule in step.errors:
            if await self._checkpoint(surface, rule.when, inputs):
                return rule
        return None

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
        surface = PlaywrightSurface(self.headless)
        try:
            self.policy.authorize_url(artifact.application.base_url)
            await surface.start(artifact.application.base_url)
            evidence.event("replay.started", capability=artifact.qualified_id, inputs=inputs)
            for step in artifact.steps:
                evidence.event("step.started", step_id=step.id, action=step.action)
                try:
                    self.policy.authorize_step(step)
                    error_rule = await self._check_errors(surface, step, inputs)
                    if error_rule and error_rule.category == ErrorCategory.BUSINESS:
                        result.status = RunStatus.BUSINESS_OUTCOME
                        result.business_code = error_rule.code
                        result.completed_at = datetime.now(UTC)
                        evidence.event("business_outcome", code=error_rule.code, step_id=step.id)
                        return result
                    if step.action == ActionType.NAVIGATE:
                        assert surface.page
                        url = self._render(step.value, inputs)
                        self.policy.authorize_url(url)
                        await surface.page.goto(url)
                    elif step.action == ActionType.CLICK:
                        await surface.click(step.target)
                    elif step.action == ActionType.TYPE:
                        await surface.type(step.target, self._render(step.value, inputs))
                    elif step.action == ActionType.WAIT:
                        assert surface.page
                        await surface.page.wait_for_timeout(int(step.value or "500"))
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
                        if error_rule.recovery == "pause":
                            screenshot = await evidence.screenshot(surface.page, f"pause-{step.id}")
                            item = interventions.create(
                                run_id,
                                error_rule.message,
                                step_id=step.id,
                                screenshot=screenshot,
                                state=await surface.observe(),
                            )
                            result.intervention_id = item.id
                            evidence.event(
                                "control.transferred", owner="human", intervention_id=item.id
                            )
                            await interventions.wait_for_resume(item.id)
                            evidence.event(
                                "control.transferred",
                                owner="automation",
                                intervention_id=item.id,
                            )
                            evidence.event("resume.observed", state=await surface.observe())
                            continue
                        raise RuntimeError(error_rule.message)
                    if step.checkpoint and not await self._checkpoint(
                        surface, step.checkpoint, inputs
                    ):
                        raise AssertionError("step checkpoint failed")
                    evidence.event("step.completed", step_id=step.id)

                except PolicyViolation:
                    raise
                except Exception as exc:
                    screenshot = await evidence.screenshot(surface.page, f"failure-{step.id}")
                    raise StepFailure(step.id, str(exc), screenshot) from exc

            if not await self._checkpoint(surface, artifact.success, inputs):
                raise StepFailure(
                    "success",
                    "final checkpoint failed",
                    await evidence.screenshot(surface.page, "failure-final"),
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
                category=ErrorCategory.CHECKPOINT,
                code="REPLAY_STEP_FAILED",
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
    def __init__(self, step_id: str, message: str, screenshot: str) -> None:
        self.step_id = step_id
        self.message = message
        self.screenshot = screenshot
        super().__init__(message)
