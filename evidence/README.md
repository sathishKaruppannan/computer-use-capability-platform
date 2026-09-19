# Evidence

Run `scripts/capture_evidence.sh` after adding `ANTHROPIC_API_KEY` to `.env`.
It creates a real Claude discovery trace, the emitted artifact, deterministic replay traces,
a business-outcome replay, and screenshots on failure under `evidence/runs/`.

Do not commit credentials, cookies, or real customer data. The demo identifiers are synthetic.

## Committed replay evidence (Phase 3)

The following runs were captured against the live demo app (`uv run uvicorn demo_app.app:app
--port 8001`), with `HEADLESS=true`, using **no LLM** — pure deterministic replay via
`ReplayEngine`. No discovery run is included yet; that requires a real `ANTHROPIC_API_KEY` and
is deferred to a later phase.

| Run ID | Scenario | Command | Result |
|---|---|---|---|
| `8b948227-8535-4cda-95e0-8c6453c7c39f` | Success | `capability-platform replay lookup-member-savings-balance.v1 --input memberId=10002` | `status=success`, `savingsBalance=1220.0` |
| `5cacf6fc-0876-4086-b2c8-7f7bfd3415f8` | Business outcome | `capability-platform replay lookup-member-savings-balance.v1 --input memberId=99999` | `status=business_outcome`, `business_code=MEMBER_NOT_FOUND` |
| `e97ff371-56e1-4e5f-bfde-5386983d8e5e` | Input validation failure (no browser launched) | `capability-platform replay lookup-member-savings-balance.v1` (no `--input`) | `status=failure`, `error.category=validation`, `error.code=MISSING_INPUT` |
| `33549c65-2899-4885-a091-c858bfb6dd94` | Injected hard failure (broken locator) | One-off script executing the artifact with `steps[0].target` pointed at a nonexistent label | `status=failure`, `error.category=checkpoint_failed`, `error.step_id=enter-member`, screenshot at `failure-enter-member.png` |

Each run directory contains `events.jsonl` (structured, redacted log of every step) and, for
the hard-failure run, a full-page screenshot of the state at the point of failure.

## Committed discovery evidence (Phase 4)

A genuine Claude-driven discovery run against the live demo app, goal: *"Find member 10001 and
return the current savings balance."* Two real attempts were made; the first failed for a real
reason (see below, not fabricated), which was diagnosed and fixed in `agent/discovery.py`
before the second, successful attempt.

| Run ID | Result | Notes |
|---|---|---|
| `1b835d17-a5f4-4206-a7eb-8b94aaab1934` | **Real failure** — `KeyError: 'strategy'` | Claude's 4th decision (`extract`) put the observed value `"$4,250.25"` directly into the `output` field instead of providing a `strategy`/`value` locator, because neither the tool schema nor the system prompt said `output` was a field *name*, not the value. Crashed before an artifact was produced. Evidence for steps 0-3 (which succeeded) is preserved in this run's `events.jsonl`. |
| `aceafd67-b8af-46bd-826a-e914d9d4f596` | Discovery **succeeded** (schema-valid artifact produced) but the artifact was flawed | After fixing the crash (clarified prompt/schema, added a defensive check), discovery completed, but the `extract` step's locator was `strategy=text, value="$4,250.25"` — the literal balance for member 10001. This overfits to one input and cannot generalize (replay for a different member would fail to find that exact text). |
| `8dcc3190-6b05-44b5-b44b-99cb0292153e` | Discovery **succeeded** with a generalizable artifact | After adding an `xpath` locator option to the tool schema and prompting Claude to reference the stable "Primary Savings" row label instead of the volatile balance text, and after fixing `_enrich_errors` to attach the `MEMBER_NOT_FOUND` rule to every post-search step (not just the last), Claude produced `extract` step `strategy=xpath, value=//tr[td[contains(.,'Primary Savings')]]/td[2]` — a locator relative to a label that's stable across members. This is the artifact now saved at `artifacts/lookup-member-savings-balance.v1.json`. |

Requirement checks against the successful run (`8dcc3190-...`):
- **No LLM key printed/logged**: confirmed by grep — the raw key value appears nowhere in `events.jsonl`, `artifact.json`, or anywhere else in the repo outside the gitignored `.env`.
- **Real observe-decide-act loop**: 4 rounds of `discovery.observed` → `discovery.decided` → `discovery.acted`, each a real `messages.create` call (not scripted).
- **Browser observations treated as untrusted data**: the model can only choose from a fixed enum of actions via forced tool-use (`tool_choice`); nothing in the observed page text is ever executed as an instruction.
- **Checkpoint verified before completion**: `agent/discovery.py`'s `complete` branch now asserts `surface.visible(success_target)` (the "Savings Account" heading) before accepting completion — previously this was not checked at all (a real gap found and fixed in this phase).
- **No model transcript persisted as the capability**: `artifact.json` contains only typed steps/locators/checkpoints — no chat history or raw model text.
- **No credentials/PII in the artifact**: confirmed by manual inspection and grep.
- **`{{memberId}}` parameterization**: `step-1.value == "{{memberId}}"`.

**Replay of the generated artifact for member 10002 (no LLM)**, run after discovery:

| Run ID | Input | Result |
|---|---|---|
| `c5c43265-c4ce-486c-aee6-c600de73faa1` | `memberId=10002` | `status=success`, `savingsBalance=1220.0` — the discovery-generated artifact, discovered against member 10001, correctly replays for a different member with no LLM involved. |
| `ff5b2a3c-2e61-4520-b8cc-d83fbf528eef` | `memberId=99999` | `status=business_outcome`, `business_code=MEMBER_NOT_FOUND` |

## Same-session human-in-the-loop handoff (Phase 5)

A controlled, injected interruption: member `10003` (`demo_app/app.py`) always returns an
unexpected "Session Notice" interstitial on search — a stand-in for a real unexpected dialog.
An error rule (`category=recoverable, recovery=pause`) added to the "click Search" step detects
it and pauses. Two real runs, both against the live demo app, no LLM involved:

| Run ID | Scenario | Result |
|---|---|---|
| `d552746b-2090-403f-b341-befcbfeb5f7e` | Human dismisses the interstitial on the same page, then resumes | `status=success`, `savingsBalance=875.5`. Full control-transfer sequence in `events.jsonl`: `step.started(step-2)` → `intervention.created` (run/capability/step/reason/state/screenshot) → `control.transferred(human)` → *(human clicks "Continue" on the exact same `Page` object, obtained via `interventions.get_page()`)* → `control.transferred(automation)` → `resume.observed` (accessibility snapshot shows the interstitial is genuinely gone) → `resume.validated` → `step.started(step-3)` → ... → `replay.completed`. |
| `cf0a404b-0fc5-4848-9a79-2b19d543b574` | Human resumes **without** dismissing the interstitial | `status=failure`, `error.category=checkpoint_failed`, `error.message="Interruption at step 'step-2' was not resolved before resume — the condition is still present"`, with a fresh screenshot. Proves the re-validation step (requirement: "re-observe and validate before continuing") isn't a no-op — a bad resume is caught, not silently accepted. |

**Same-session, not a new browser**: `InterventionManager` now holds a live `Page` handle
per intervention (`_pages`, in-process only, never serialized into the `Intervention` model or
any API/evidence payload) so a same-process actor can fetch the *exact* page the paused run is
using — confirmed in the first run above by observing the page's URL and DOM state before and
after the human's action, with no `surface.start()`/`close()` in between (the `PlaywrightSurface`
instance is created once per replay and only closed at the very end).

Automated test coverage: `tests/test_intervention.py` (2 tests, `@pytest.mark.e2e`) — the happy
path above, and the negative path (resume without resolving).

## Precise error categories: auth and timeout, no longer collapsed into "checkpoint" (post-review follow-up)

Real gap found by direct inspection (`grep -n "ErrorCategory\." computer_use/replay.py`), the
same class of gap as the earlier dead `RECOVERABLE` enum member: `AUTH`, `TARGET_NOT_FOUND`,
`TIMEOUT`, and `APPLICATION` were all declared in the taxonomy but **never assigned anywhere**.
A declared error rule with any category other than `business` (e.g. a session-expired state
classified `auth`) silently collapsed into the generic `checkpoint_failed` bucket the moment it
fell through to a hard failure — its own category was discarded. Fixed two ways:

1. **Declared rules now keep their own category.** `StepFailure` carries `category`/`code`
   through; a matched rule that isn't business/retry/pause raises with its *own* declared
   category instead of a hardcoded `checkpoint_failed`.
2. **Driver-level timeouts get their own category too**, without reintroducing a Playwright
   dependency into `replay.py` — `PlaywrightSurface` (the adapter, per T18) translates
   Playwright's own `TimeoutError` into a domain-level `SurfaceTimeout`, which `ReplayEngine`
   catches and classifies as `ErrorCategory.TIMEOUT`. A `LookupError` (locator genuinely not
   found) is now classified `target_not_found` rather than the generic `checkpoint_failed` too
   — a real, intentional behavior change to an existing test (`test_replay_structured_failure_on_broken_locator`),
   confirmed to be a *more* accurate classification, not a regression.

Real run: `evidence/runs/853ab821-388a-4ba6-83e4-8b762d5508ad/` — a simulated expired session
(member `10005` in `demo_app.py`, added for this purpose) with a declared `ErrorRule(category=
AUTH, code="SESSION_EXPIRED")` correctly fails as `category=auth`, not `checkpoint_failed`.
`tests/test_replay_error_categories.py` covers both: the real AUTH scenario against the live
demo app, and a deterministic TIMEOUT classification test using a fake `SurfaceAdapter` whose
`click()` raises `SurfaceTimeout` (no flaky real browser timing needed to prove the mapping).

## Discovery-side risk classification (post-review follow-up)

Real gap found while stress-testing the "risky action" requirement: `agent/discovery.py`
hardcoded `risk=RiskLevel.READ_ONLY` on **every** step, regardless of what it actually did —
meaning the whole approval gate built for T6 could never trigger from genuine discovery output;
it only ever fired in tests that manually bumped a step's risk. Fixed with a deterministic,
code-side classifier (`ClaudeDiscoveryAgent._classify_risk`) — deliberately *not* left to the
model to self-judge, matching the project's "policy is independent of model planning" principle
even at the point risk is first assigned. `EXTRACT`/`WAIT`/`NAVIGATE` → `read_only`;
`TYPE`/`SELECT` → `reversible` (data entered, nothing committed yet); `CLICK` → `risky` if the
button's accessible name/label matches a mutating-action keyword list (save, submit, update,
delete, confirm, pay, transfer, ...), else `read_only`.

Proven end-to-end against the real demo app, not just as a unit-tested function: run
`c21fe518-9fbc-4bbc-a565-9aa2e91baaa5` classifies a click on a hypothetical "Update Phone
Number" button as `risky` exactly the way discovery now would, and confirms `ReplayEngine`'s
real approval gate fires for it (`intervention.created` with the correct reason/step/state,
approved, then completes: `savingsBalance=1220.0`). `tests/test_discovery_risk_classification.py`
covers the classifier directly (11 parametrized cases) plus this same full-chain proof.

## OpenAI GPT-5 mini as a per-call discovery fallback (post-review follow-up: closing T17)

Claude remains the primary discovery provider. If a single Anthropic call errors mid-run (any
`anthropic.APIError` — connection, timeout, rate limit, 5xx, auth), that one decision falls back
to GPT-5 mini instead of aborting the whole discovery run. Verified genuinely, not simulated:

1. Confirmed the OpenAI key works with a real minimal call, then with the actual
   `browser_action` tool-calling shape used by discovery — GPT-5 mini correctly returned
   `strategy=role, value=textbox, name="Member Number"` on the first attempt.
2. Ran real discovery with Anthropic **deliberately broken** (`CLAUDE_MODEL=claude-invalid-model-xyz`,
   a genuine model name that doesn't exist — a real 404 from the real Anthropic API, not a mock)
   while OpenAI stayed correctly configured. Every one of the 6 decision rounds hit the real
   Anthropic error and fell back to a real GPT-5 mini call. Run
   `evidence/runs/484a2e8c-e7d8-498d-a4a6-2ee41fb1d0c0/`:
   - `discovery.provider_fallback` events show the real error
     (`"Error code: 404 - ... 'message': 'model: claude-invalid-model-xyz'"`) and
     `from_provider`/`to_provider`.
   - The resulting artifact's `discovered_by` field accurately records
     `"anthropic:claude-invalid-model-xyz+openai:gpt-5-mini (fallback used)"` — a real bug
     (found immediately, before it could go undetected) where this field was hardcoded to only
     ever say `anthropic:...` regardless of which provider actually made the decisions, fixed
     before this evidence was captured.
   - GPT-5 mini produced a fully correct, generalizable artifact on the first attempt — correct
     `role`/`name` pairing throughout, and the stable `xpath` locator for the one
     input-dependent value (`//tr[td[contains(.,'Primary Savings')]]/td[2]`) — the same quality
     bar Claude itself needed two attempts to reach in Phase 4.
3. Replayed the resulting artifact for member 10002 with no LLM involved
   (`evidence/runs/316da14b-.../`): `status=success, savingsBalance=1220.0`.

Automated tests (`tests/test_discovery_fallback.py`, 3 tests) use mocked clients so they run in
CI without real keys: fallback triggers on a real-shaped Anthropic error, the fallback correctly
re-raises if no OpenAI key is configured (no silent swallow), and — importantly — OpenAI is
*never* called when Anthropic succeeds (asserted directly, not just assumed).

## Risky-action approval flow (post-review follow-up: closing T6)

The PDF (§3.4) leaves the mechanism for handling risky/irreversible actions entirely open
("block, require confirmation, or flag — your call, justify it"). Implemented "require
confirmation" by reusing the same same-session intervention mechanism as an
unexpected-condition handoff, rather than building a second escalation path: before a
risky/irreversible step runs, `ReplayEngine` pauses and creates an intervention; a human
approves or denies via `interventions.resume(id, approved=True|False)` (REST:
`POST /interventions/<id>/resume` with `{"approved": true|false}`); a denial fails the run with
a structured `APPROVAL_DENIED` error rather than proceeding.

Two real runs, both against the live demo app, no LLM involved (member `10002`'s "click Open
Accounts" step temporarily marked `risky` for the test):

| Run ID | Scenario | Result |
|---|---|---|
| `1c3f0f3a-1010-4e66-bb27-4ca28d6fd17a` | Human approves | `status=success`, `savingsBalance=1220.0`. Intervention carried full context (`reason="Step 'step-3' is risky and requires human approval before it runs"`, accessibility state, screenshot). |
| `573ee8cd-0958-4ead-9db8-d4e321af9b8c` | Human denies | `status=failure`, `error.category=policy`, `error.code=APPROVAL_DENIED`, with a fresh screenshot at the point of denial — not silently treated as approved. |

Automated tests: `tests/test_approval.py` (2 tests, `@pytest.mark.e2e`) — both outcomes above.

## Automated wait/retry recovery (post-review follow-up: closing T4)

The PDF glossary's own example of a "recoverable condition" is "wait/retry a transient load" —
previously declared in the schema (`ErrorRule.recovery: "retry"`) but never dispatched by the
executor. Fixed in `computer_use/replay.py`; demonstrated with a real run: member `10004`'s
search result always shows a "Loading member details..." banner that clears itself client-side
after 1.2s (`demo_app/app.py`), no human involved.

Run `d77a2c55-6ffd-40f7-b0e4-f7cdf35a90f4`: 3 `recoverable.retry` events (500ms apart) then
`recoverable.resolved`, then `status=success, savingsBalance=3300.0`. Automated tests:
`tests/test_replay_recoverable.py` (success within budget, and a negative case where the budget
is deliberately too small and the run fails hard with a clear message rather than hanging or
silently succeeding).

## User-reported failure, diagnosed and fixed (Phase 4b)

Running the same discovery goal again (user-triggered), a fourth real run
(`4bb650a8-1609-43fe-822c-0feba1697827`) failed with `LookupError: role:Search matched 0`.
Diagnosis: Claude's decision was `{"strategy": "role", "name": "button", "value": "Search"}` —
`value`/`name` swapped for the `role` strategy, where `value` must be the ARIA role type and
`name` the accessible label. The tool schema didn't state this per-strategy rule clearly enough.
Fixed in `agent/discovery.py` (explicit rule + worked example in both the prompt and the schema
field descriptions). Re-run afterward with the same goal succeeded
(`created_at: 2026-09-13T21:50:26Z`), and replay for member 10002 against the regenerated
artifact returned `status=success, savingsBalance=1220.0` (run `226215df-...`).

**Note on two older evidence runs** (`c1dbc057-d8de-4304-9c34-36c3ff5750dd`,
`ee6e3d89-0b83-4b5a-9166-7ee4b8e83734`): these use the pre-Phase-4 artifact's step IDs
(`enter-member`, `search`, ...) and were not produced by a command run explicitly in this
session's visible history — they appear to be from an automated background pass earlier in the
session. Their content is genuine (real successful/business-outcome replays against the live
demo app), just predating the artifact regenerated in this phase. Left in place rather than
deleted, since they are real runs, not fabricated ones.

## Goal-driven pipeline, guardrails, and natural-language synthesis (later session work)

`AgentOrchestrator` (Intent Analyzer → Planner → PlanValidator → CapabilityResolver → Executor →
`GroundedSynthesizer`, `agent/orchestrator.py`) replaced "every goal goes straight to discovery."
The runs below are real interaction traces from live use of the admin console chatbot
(`GET /admin`) during this same session — not scripted for evidence. Two real bugs are captured
here exactly as found, each with a follow-up run showing the corrected text, same precedent as
the Phase 4b discovery-failure diagnosis above: kept rather than deleted.

### Grounded-synthesis fact-dropping bug, found and fixed

`GroundedSynthesizer`'s SUCCESS branch used to filter its fact list through the LLM-derived
`TaskIntent.required_outputs` field instead of the deterministic `outputs` dict the aggregator
already computed — for a goal phrased tersely enough that the model's own output naming didn't
exactly match the plan's key, this silently dropped a value that had already been computed
correctly, right next to a trace panel proving it.

| Run ID | Stage | `result.synthesized.text` |
|---|---|---|
| `8e46424a-9439-4ab6-a78f-f452149eeafd` | Bug, live | `Completed 'retrieve_account_balance'. ` — value silently dropped |
| `313b6989-be8c-4e56-9fbe-a14db2792812` | Fixed (raw values), before naturalization | `Completed 'retrieve_account_balance'. savingsBalance: 4250.25` |
| `d88ce1db-9ff9-446d-be77-c9d0861a8fdf` | Fixed and reworded to read naturally | `The savings balance is 4250.25.` |

### FAILURE text leaking internal details, found and fixed

A goal with no sensible business meaning on the target correctly failed clean (no crash — the
`DISCOVERY_FAILED` guardrail from earlier in this same phase working exactly as designed), but
the message text itself leaked a raw Python exception class name and a raw snake_case intent id.

| Run ID | Stage | `result.synthesized.text` |
|---|---|---|
| `bc0fa3df-26cd-4ff7-a029-1514a71ee5f5` | Bug, live (`open su account for 10001`) | `Could not complete 'open_account': Could not find or create a capability for this goal (LookupError). ...` |
| `2450b42c-f3da-4626-bce2-210a954ef8ae` | Fixed (`open sub account for 10001`) | `Could not complete 'open sub account': Could not find or create a capability for this goal. ...` — no exception class name, humanized intent |

Also genuinely captured, the same guardrail on a different unresolvable goal —
`503aee37-a90b-48c0-8981-6de82ca566ad` ("reticulate splines for member 10001"): clean
`DISCOVERY_FAILED`, never an unhandled 500 (the original bug this guardrail was built to fix).

### Conversational message misclassified as clarification, found and fixed

A plain "thank you"-style follow-up (no task content at all) was routed through the ambiguous-goal
`requires_clarification` guardrail instead of getting a plain acknowledgment — technically
defensible (the message genuinely isn't a task) but poor chat UX.

`a5678129-df7f-474f-b816-cc29abdf1930`: `intent.clarification_required` event, `question: "This
appears to be an acknowledgment of a previous response. Is there anything else you would like me
to help you with?"` — the exact live run behind the bug report. Fixed by adding a third
guardrail-shaped flag, `TaskIntent.is_conversational`, checked before this branch is reached; see
`TASKS.md`'s phase log for the live-verified fix (re-run against isolated servers/data outside
this repo, so no "after" run is committed here — the "before" bug run above is real and kept for
the same reason the Phase 4/4b discovery failures above were kept).

### Ambiguous-goal clarification, working as designed

Two more genuine examples of `requires_clarification` correctly triggering for goals that really
are unclassifiable: `5aafbc96-6895-4184-af99-85b6e1acb262` and
`a614d492-7081-4b52-a051-8bb93a64ec47`, both `question: "What would you like help with today?"`.

**Redaction check**: `uv run python scripts/validate_evidence.py` passed against the full
`evidence/` tree (266 text files, 0 issues) before any of the runs above were committed.

