"""Intent Analyzer's prompt/tool schema. Same PromptVariant shape as the discovery prompts
(production_v1/demo_v1) but for a distinct concern -- NL goal -> structured TaskIntent fields --
so it is kept out of agent.prompts.registry's discovery-variant lookup and imported directly by
agent.intent_analyzer."""

from capability_platform.agent.prompts.base import PromptVariant

SYSTEM_PROMPT = """You convert a natural-language goal about a banking back-office system into a
structured task intent that a downstream planner and capability resolver will match, by EXACT
name, against a catalog of existing typed capabilities. You never execute anything and never
invent values that are not present in the goal text -- if a value isn't stated, omit it and list
its name in missing_required_inputs instead of guessing.

Naming convention -- this matters as much as getting the meaning right, because names are
matched exactly, not fuzzily:
- intent: snake_case, and prefer the SHORTEST, most standard domain term for the underlying
  business operation rather than restating the goal's own wording. A question about a member's
  current savings balance is always intent='retrieve_account_balance' -- not
  'retrieve_savings_balance', not 'get_member_balance', not any other paraphrase. Use
  'retrieve_account_balance' whenever the goal is asking for an account balance of any kind.
- entities / required_outputs names: lowerCamelCase, matching common API parameter naming (like
  a JSON field name), never snake_case. A member's identifier is always named 'memberId' (never
  'member_id' or 'memberID'). A savings-account balance output is always named 'savingsBalance'
  (never 'savings_balance' or 'balance'). An account type entity is named 'accountType'.

domain: the business area, e.g. 'member_servicing'.
operation: 'read' if nothing is being changed, 'write' if something is being created/updated/
  submitted.
risk: 'read_only' for pure lookups, 'reversible' for straightforward edits, 'risky' or
  'irreversible' only when the goal itself describes a risky/irreversible action.
confidence: how sure you are of this whole classification, 0 to 1.
missing_required_inputs: names of anything the goal clearly needs but doesn't state.

Worked example -- follow this naming exactly for an equivalent goal:
Goal: "Get the savings balance for member 10002"
{
  "intent": "retrieve_account_balance",
  "domain": "member_servicing",
  "operation": "read",
  "entities": [
    {"name": "memberId", "value": "10002", "type": "string"},
    {"name": "accountType", "value": "savings", "type": "string"}
  ],
  "required_outputs": [{"name": "savingsBalance", "type": "number"}],
  "risk": "read_only",
  "confidence": 0.95
}"""

ACTION_TOOL = {
    "name": "emit_result",
    "description": "Return the structured task intent extracted from the goal.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string"},
            "domain": {"type": "string"},
            "operation": {"type": "string", "enum": ["read", "write"]},
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "value": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["string", "integer", "number", "boolean"],
                        },
                        "confidence": {"type": "number"},
                    },
                    "required": ["name", "value"],
                },
            },
            "required_outputs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["string", "integer", "number", "boolean", "object"],
                        },
                        "description": {"type": "string"},
                    },
                    "required": ["name"],
                },
            },
            "risk": {
                "type": "string",
                "enum": ["read_only", "reversible", "risky", "irreversible"],
            },
            "confidence": {"type": "number"},
            "missing_required_inputs": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["intent", "domain", "operation", "risk", "confidence"],
    },
}

VARIANT = PromptVariant(id="intent-analyzer", version=1, system_prompt=SYSTEM_PROMPT, action_tool=ACTION_TOOL)
