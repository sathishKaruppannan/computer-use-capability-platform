import re
from typing import TYPE_CHECKING, Any

from capability_platform.models import ExecutionResult, RunStatus

if TYPE_CHECKING:
    from capability_platform.agent.models import CapabilityExecutionResult, TaskIntent


def _humanize(name: str) -> str:
    """'savingsBalance' -> 'savings balance', 'noteId' -> 'note id' -- purely mechanical
    camelCase word-splitting, no per-output dictionary. Generalizes to any future capability's
    output names without hardcoding any one of them (CLAUDE.md's "no source-specific branching"
    rule, applied to response text instead of routing logic)."""
    words = re.findall(r"[A-Z][a-z0-9]*|[a-z0-9]+", name)
    return " ".join(word.lower() for word in words) if words else name


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
        if intent.is_conversational:
            # A greeting/thanks/acknowledgment, not a task -- the orchestrator built a real but
            # empty plan for this (see _intent_plan_resolve), so status is always a bare SUCCESS
            # with no outputs here; echoing "Completed 'unknown'." would be nonsense. Read from
            # `intent`, not a new parameter -- same class of read as intent.intent/
            # intent.required_outputs below, so this doesn't reopen the no-LLM-parameter guarantee.
            return intent.conversational_reply or "Got it -- let me know if there's anything else I can help with."
        if status == RunStatus.SUCCESS:
            # Iterate `outputs` itself, not `intent.required_outputs` -- `outputs` is the
            # deterministic aggregator's canonical result (agent/orchestrator.py::_aggregate,
            # exact-key lookups against the PLAN's produced_outputs, no LLM involved). A real bug,
            # found live: `intent.required_outputs` is an LLM-derived field, and for a terse goal
            # ("account id 10001 balance") it can come back empty or differently-named than the
            # plan's own output key -- filtering through it silently dropped a fact that was
            # already computed correctly. `outputs` is already the trustworthy, complete set;
            # nothing about grounding is lost by not re-filtering it through an LLM-derived list.
            #
            # The raw value itself (`value` below) is never reformatted -- it's interpolated
            # exactly as computed, which is what keeps this "grounded": a reviewer can grep the
            # response text for the literal number/string that actually came out of replay.
            # `_humanize(name)` only touches the LABEL next to it ("savingsBalance" ->
            # "savings balance"), never the value.
            if not outputs:
                action = intent.intent.replace("_", " ")
                return f"Done -- '{action}' completed, with nothing further to report."
            facts = ", ".join(f"the {_humanize(name)} is {value}" for name, value in outputs.items())
            return facts[0].upper() + facts[1:] + "."
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
        action = intent.intent.replace("_", " ") if intent.intent != "unknown" else "this request"
        for result in execution:
            if result.status == RunStatus.FAILURE and result.error:
                return f"Could not complete '{action}': {result.error.message}"
        return f"Could not complete '{action}': see execution details for the failing step."
