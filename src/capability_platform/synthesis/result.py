from typing import TYPE_CHECKING, Any

from capability_platform.models import ExecutionResult, RunStatus

if TYPE_CHECKING:
    from capability_platform.agent.models import CapabilityExecutionResult, TaskIntent


class GroundedSynthesizer:
    """Formats only canonical execution facts; it cannot create domain values."""

    @staticmethod
    def synthesize(result: ExecutionResult) -> str:
        if result.status == RunStatus.SUCCESS:
            facts = ", ".join(f"{key}: {value}" for key, value in result.outputs.items())
            return f"Capability completed successfully. {facts}"
        if result.status == RunStatus.BUSINESS_OUTCOME:
            return (
                f"The application returned the expected business outcome: {result.business_code}."
            )
        if result.status == RunStatus.PAUSED:
            return f"Automation paused for human intervention {result.intervention_id}."
        return f"Capability failed: {result.error.code if result.error else 'UNKNOWN'} - {result.error.message if result.error else 'No detail'}"

    @staticmethod
    def synthesize_agent_result(
        intent: "TaskIntent",
        outputs: dict[str, Any],
        status: RunStatus,
        business_code: str | None = None,
        execution: "list[CapabilityExecutionResult] | None" = None,
    ) -> str:
        """Same contract as synthesize(): formats only canonical values already computed by the
        deterministic aggregator, via exact-key interpolation. Deliberately takes no LLMProvider
        and makes no LLM call -- there is no parameter here through which any provider's raw
        output (however adversarial) could reach a numeric/entity value in the returned text.
        `execution` is optional and, like everything else here, only ever read from -- the extra
        step-level detail it carries (a freshly discovered artifact's id, a specific error
        message) is canonical fact already computed elsewhere, not derived here."""
        execution = execution or []
        if status == RunStatus.SUCCESS:
            facts = ", ".join(
                f"{name}: {outputs[name]}"
                for name in (output.name for output in intent.required_outputs)
                if name in outputs
            )
            return f"Completed '{intent.intent}'. {facts}"
        if status == RunStatus.BUSINESS_OUTCOME:
            return f"The request returned a known business outcome: {business_code}."
        if status == RunStatus.PAUSED:
            for result in execution:
                if result.status == RunStatus.PAUSED and result.raw_execution_result:
                    artifact_id = result.raw_execution_result.get("artifact_id")
                    if artifact_id and result.raw_execution_result.get("lifecycle") == "draft":
                        return (
                            f"A new capability draft ('{artifact_id}') has been created for this "
                            "goal. Please ask your admin to review and approve it, then try again."
                        )
            return "One or more steps are awaiting human approval. Please try again once an admin has resolved this."
        for result in execution:
            if result.status == RunStatus.FAILURE and result.error:
                return f"Could not complete '{intent.intent}': {result.error.message}"
        return f"Could not complete '{intent.intent}': see execution details for the failing step."
