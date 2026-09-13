from capability_platform.models import ExecutionResult, RunStatus


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
