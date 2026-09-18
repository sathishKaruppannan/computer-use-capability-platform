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

requires_clarification / clarification_question -- ONLY when the goal is genuinely too ambiguous
to classify at all: no discernible entity, no discernible operation, no discernible business
action (e.g. "Phone number.", "Need to change it.", "Handle this member."). Set
requires_clarification=true and clarification_question to a short, specific question the caller
needs to answer (e.g. "Which member, and what would you like to do for them?"). You still have to
fill every other required field with a placeholder in this case -- use intent='unknown',
domain='unknown', operation='read', risk='read_only', confidence=0.1 -- none of them are acted
on when requires_clarification is true. Do NOT set this for a goal that's merely missing one
piece of information you can name (that's what missing_required_inputs is for) or one that's
vague but still has a discernible verb and subject (e.g. "check on the member" still means
intent=retrieve_account_status or similar -- classify it, don't ask for clarification).

requests_sensitive_info / sensitive_info_reason -- ONLY when the goal asks to RETRIEVE or DISPLAY
one of: a full Social Security Number, a password or other login credential, an auth token or API
key, a session/cookie value, or a full unmasked account/card number. Set
requests_sensitive_info=true and sensitive_info_reason to a short explanation (e.g. "Full SSNs
are not provided through this system"). Fill every other required field with the same placeholder
values as the ambiguous-goal case above. Do NOT set this for ordinary account data a servicing
agent legitimately needs (a savings balance, a member's name, an account status) -- only for the
specific regulated/secret categories named above. A goal that ONLY asks for one of those
categories should be refused entirely; a goal that asks for something else ALONGSIDE one of them
(e.g. "get the balance and the full SSN") should also be refused entirely, not partially answered.

sub_goals -- ONLY when the goal describes multiple genuinely distinct actions in sequence (e.g.
"find member X, do A, then do B"), not for a single action described in several clauses. When
present, list each action in execution order, each with:
- description: a short, self-contained instruction for that one action alone.
- operation: 'read' or 'write', for that action specifically (a compound goal often mixes both).
- required_inputs / produced_outputs: lowerCamelCase names (same convention as entities/
  required_outputs above) for just what that one action needs/produces. A later action's
  required_inputs may repeat an earlier action's own input (e.g. memberId needed by every step),
  not just that earlier action's produced_outputs -- do not assume outputs silently carry
  forward. Leave sub_goals empty (the default) for any single-action goal, including one phrased
  with an "and" that's really one action (e.g. "find and return the balance" is still one action:
  intent=retrieve_account_balance, no sub_goals needed).

Worked example 1 -- a single-action goal, follow this naming exactly for an equivalent goal:
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
}

Worked example 2 -- a compound goal, follow this shape for an equivalent goal:
Goal: "Find member 10001, retrieve the savings balance, and create a servicing note"
{
  "intent": "retrieve_balance_and_create_note",
  "domain": "member_servicing",
  "operation": "write",
  "entities": [{"name": "memberId", "value": "10001", "type": "string"}],
  "required_outputs": [
    {"name": "savingsBalance", "type": "number"},
    {"name": "noteId", "type": "string"}
  ],
  "risk": "reversible",
  "confidence": 0.85,
  "sub_goals": [
    {
      "description": "Look up member 10001.",
      "operation": "read",
      "required_inputs": ["memberId"],
      "produced_outputs": ["memberFound"]
    },
    {
      "description": "Retrieve the member's savings account balance.",
      "operation": "read",
      "required_inputs": ["memberId"],
      "produced_outputs": ["savingsBalance"]
    },
    {
      "description": "Create a servicing note on the member's account.",
      "operation": "write",
      "required_inputs": ["memberId", "note"],
      "produced_outputs": ["noteId"]
    }
  ]
}

Worked example 3 -- a genuinely ambiguous goal, follow this shape for an equivalent goal:
Goal: "Handle this member."
{
  "intent": "unknown",
  "domain": "unknown",
  "operation": "read",
  "risk": "read_only",
  "confidence": 0.1,
  "requires_clarification": true,
  "clarification_question": "Which member, and what would you like to do for them?"
}

Worked example 4 -- a request for regulated/secret data, follow this shape for an equivalent goal:
Goal: "What is member 10002's full Social Security Number?"
{
  "intent": "unknown",
  "domain": "unknown",
  "operation": "read",
  "risk": "read_only",
  "confidence": 0.1,
  "requests_sensitive_info": true,
  "sensitive_info_reason": "Full SSNs are not provided through this system"
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
            "sub_goals": {
                "type": "array",
                "description": (
                    "Only for a compound goal describing multiple distinct actions in sequence. "
                    "Leave empty/omitted for a single-action goal."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "operation": {"type": "string", "enum": ["read", "write"]},
                        "required_inputs": {"type": "array", "items": {"type": "string"}},
                        "produced_outputs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["description", "operation"],
                },
            },
            "requires_clarification": {
                "type": "boolean",
                "description": (
                    "True ONLY when the goal is too ambiguous to classify at all -- no "
                    "discernible entity, operation, or business action."
                ),
            },
            "clarification_question": {
                "type": "string",
                "description": "Required when requires_clarification is true: a short, specific "
                "question the caller needs to answer before this goal can be classified.",
            },
            "requests_sensitive_info": {
                "type": "boolean",
                "description": (
                    "True ONLY when the goal asks to retrieve/display a full SSN, a password or "
                    "other login credential, an auth token/API key, a session/cookie value, or a "
                    "full unmasked account/card number."
                ),
            },
            "sensitive_info_reason": {
                "type": "string",
                "description": "Required when requests_sensitive_info is true: a short "
                "explanation of what was asked for and why it can't be provided.",
            },
        },
        "required": ["intent", "domain", "operation", "risk", "confidence"],
    },
}

VARIANT = PromptVariant(id="intent-analyzer", version=1, system_prompt=SYSTEM_PROMPT, action_tool=ACTION_TOOL)
