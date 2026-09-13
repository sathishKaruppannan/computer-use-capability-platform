# Assessment: PDF requirements vs. current implementation

Source of truth: `docs/Assignment-Computer-Use-Automation-System.pdf` ("Take-Home Project:
Computer-Use Automation System", interface.ai). This file is an **assessment only** — no
implementation changes were made while producing it. Status values: **Complete** (code + test
or runtime evidence exists), **Partial** (some but not all of the requirement is met),
**Missing** (no implementation), **Unverified** (code exists but no test/runtime evidence
confirms it works as required). Every recommended fix below stays inside the existing
architecture (`CapabilityArtifact`, `SurfaceAdapter`, `PolicyEngine`, `Redactor`,
`InterventionManager`, etc.) — no architectural changes are proposed.

## Baseline commands run for this assessment

```
uv sync --extra dev
uv run pytest -q -m "not e2e"   →  4 passed, 1 deselected   (PASS)
uv run ruff check .             →  All checks passed!        (PASS)
```
Note: the first attempt at these two commands was run in parallel and raced on the shared
`uv`-managed virtualenv, corrupting it (`ruff` binary missing, `pytest` picking up a stale
interpreter without `playwright` installed). Rebuilding the venv from scratch and running the
commands sequentially fixed this — it was a tooling artifact, not a project defect. Run these
two commands sequentially, not in parallel, when validating this repo.

## Phase 2 log — legacy demo app validation (no Anthropic API calls)

Commands executed, in order:
```
uv run playwright install chromium
uv run uvicorn demo_app.app:app --port 8001 &         # PID 46742, log: /tmp/demo_app.log

curl -s -X POST http://127.0.0.1:8001/search -d "member_id=10001"
curl -s http://127.0.0.1:8001/member/10001/accounts

curl -s -X POST http://127.0.0.1:8001/search -d "member_id=10002"
curl -s http://127.0.0.1:8001/member/10002/accounts

curl -s -X POST http://127.0.0.1:8001/search -d "member_id=99999"

uv run pytest -q -m e2e -v
uv run pytest -q -v          # full suite, demo app live
uv run ruff check .
```

Results:
| Check | Result |
|---|---|
| Demo app starts on port 8001 | PASS — `GET /` → 200 |
| Member 10001 exists | PASS — search returns "Member Details" / "Alex Morgan"; `/member/10001/accounts` → `#savings-balance` = `$4,250.25` |
| Member 10002 savings balance = 1220.00 | PASS — `/member/10002/accounts` → `#savings-balance` = `$1,220.00` |
| Member 99999 → explicit "Member not found" | PASS — search returns `Member not found` / "No record matches member number 99999" |
| Playwright E2E replay test | PASS — `tests/test_replay_e2e.py::test_replay_success` — 1 passed, 4 deselected, 2.22s. Asserts `RunStatus.SUCCESS` and `outputs["savingsBalance"] == 1220.0` against the **live** demo app (no mocks) |
| Full suite (`uv run pytest -q`) | PASS — 5 passed, 0.45s |
| Lint (`uv run ruff check .`) | PASS — All checks passed! |
| Anthropic API called during this phase | **No** — only `ReplayEngine` (no LLM dependency) was exercised; `discover`/`ClaudeDiscoveryAgent` were never invoked |

**Files changed in this phase: none.** No fixes were required — the demo app and deterministic
replay engine both worked correctly against each other on the first run. This confirms T3
("deterministic replay, no LLM in decision loop") now has a live, non-mocked runtime pass in
addition to its prior code-review confirmation.

**What this phase does *not* close:** the e2e test writes its evidence to pytest's ephemeral
`tmp_path`, not to the committed `evidence/` directory, so T8/T12/T15 (evidence must be
committed under `/evidence/`) remain open — this run proves the mechanism works, but nothing
from it was persisted to the repo. T1 (genuine discovery run) is untouched by design, since
this phase explicitly excluded Anthropic API calls.

Demo app is still running in the background (PID 46742, port 8001, log at
`/tmp/demo_app.log`) in case Phase 3 needs it live; stop it with `kill 46742` if not needed.

## Phase 3 log — deterministic replay validation (no discovery, no Anthropic calls)

Commands executed, in order (demo app already running on port 8001 from Phase 2):
```
uv run pytest -q -v                          # full suite incl. new scenario tests
uv run ruff check .

HEADLESS=true uv run capability-platform replay lookup-member-savings-balance.v1 --input memberId=10002
HEADLESS=true uv run capability-platform replay lookup-member-savings-balance.v1 --input memberId=99999
HEADLESS=true uv run capability-platform replay lookup-member-savings-balance.v1   # no --input, triggers validation failure
HEADLESS=true uv run python3 -c "<inline script executing a copy of the artifact with a broken locator>"
```

**Real gap found during this phase that Phase 1's assessment missed:** the PDF's mandatory
examples of runtime conditions to detect explicitly include "a validation error," but
`ReplayEngine.execute` never checked artifact inputs against `ParameterSpec.required`/`.pattern`
before touching the browser — a malformed `memberId` would have gone straight to the live page
and failed as an opaque locator/checkpoint error instead of a clean, up-front validation
failure. Fixed in this phase (see "Files changed" below); tracked as **T23**.

**Files changed in this phase:**
- `src/capability_platform/models.py` — added `ErrorCategory.VALIDATION = "validation"`.
- `src/capability_platform/computer_use/replay.py` — added `ReplayEngine._validate_inputs()`,
  called before `PlaywrightSurface` is even constructed, so a validation failure never opens a
  browser. Returns `RunError(category=VALIDATION, code="MISSING_INPUT"|"INVALID_INPUT", ...)`.
- `tests/test_replay_validation.py` (new) — 2 tests for missing/invalid input, run in the
  default (non-`e2e`) suite since no browser is launched on this path.
- `tests/test_replay_e2e.py` — added `test_replay_business_outcome_member_not_found`,
  `test_replay_structured_failure_on_broken_locator`,
  `test_replay_never_instantiates_llm_client`; strengthened `test_replay_success` with an
  output-type assertion against the artifact's declared `OutputSpec`.
- `.gitignore` — removed the `evidence/runs/` exclusion so real evidence can be committed
  (closing part of T12/T15's root cause).
- `evidence/README.md` — documented the four real replay runs captured below.
- No changes to `agent/discovery.py`, `demo_app/app.py`, or any Anthropic-related code.

**Required scenario results:**
| # | Scenario | Result |
|---|---|---|
| 1 | `memberId=10002` → success, `savingsBalance=1220.0` | PASS — `tests/test_replay_e2e.py::test_replay_success` + real CLI run `8b948227-...` (see `evidence/runs/`) |
| 2 | `memberId=99999` → `business_outcome` / `MEMBER_NOT_FOUND` | PASS — `test_replay_business_outcome_member_not_found` + real CLI run `5cacf6fc-...` |
| 3 | Invalid target / injected condition → structured failure with step + screenshot | PASS — `test_replay_structured_failure_on_broken_locator` + real run `33549c65-...`, `error.step_id="enter-member"`, screenshot at `evidence/runs/33549c65-.../failure-enter-member.png` |
| 4 | Prove replay never instantiates/calls an LLM client | PASS — new test `test_replay_never_instantiates_llm_client` monkeypatches `anthropic.AsyncAnthropic`/`Anthropic` to raise if constructed; a full successful replay completes without tripping it (replay's own import graph never references `anthropic` at all, confirmed separately in Phase 1) |
| 5 | Validate inputs against the artifact contract before browser execution | **Was missing, now implemented** — `_validate_inputs` runs first; real CLI run `e97ff371-...` shows `status=failure`/`error.category=validation` with no `evidence_path` (no browser/screenshot involved) and 2 dedicated offline tests |
| 6 | Verify final success checkpoint + declared output types | PASS — success test now asserts `isinstance(outputs["savingsBalance"], float)` and cross-checks it against the artifact's own `OutputSpec.type == "number"` |
| 7 | Add/improve automated tests | Done — test count went from 5 to 10 (`test_replay_validation.py` ×2 new, `test_replay_e2e.py` ×3 new + 1 strengthened) |
| 8 | Update TASKS.md and evidence documentation | This section + `evidence/README.md` update |

**Full suite result:** `10 passed in 3.02s` (`uv run pytest -q -v`). **Lint:** `All checks
passed!` (`uv run ruff check .`). Anthropic API was not called at any point in this phase.

**What this phase does *not* close:** T1 (genuine discovery run) is still open by design —
this phase excluded Anthropic calls entirely. T12/T15 (evidence) are now **partially** closed:
real, committed replay-side evidence exists for success/business-outcome/validation-failure/
hard-failure, but discovery-run evidence is still outstanding.

## Phase 4 log — genuine Claude discovery + validation (real Anthropic API calls made)

Goal used: *"Find member 10001 and return the current savings balance."*

**Commands executed, in order** (demo app live on port 8001; `ANTHROPIC_API_KEY` added to the
gitignored `.env` by the user, never printed or logged by any command below):
```
HEADLESS=true uv run capability-platform discover --goal "..." --member-id 10001   # attempt 1: crashed (real failure)
# diagnosed: agent/discovery.py fixed (prompt/schema clarity + defensive check)
HEADLESS=true uv run capability-platform discover --goal "..." --member-id 10001   # attempt 2: succeeded, but locator overfit to one input
# diagnosed: agent/discovery.py fixed (xpath locator option + error-rule attachment)
HEADLESS=true uv run capability-platform discover --goal "..." --member-id 10001   # attempt 3: succeeded, generalizable artifact
uv run capability-platform list                                                    # validates via CapabilityArtifact
HEADLESS=true uv run capability-platform replay lookup-member-savings-balance.v1 --input memberId=10002
HEADLESS=true uv run capability-platform replay lookup-member-savings-balance.v1 --input memberId=99999
uv run pytest -q -v
uv run ruff check .
```

**Real failure #1 (not fabricated) — diagnosed and fixed:** the first discovery attempt crashed
with `KeyError: 'strategy'` on Claude's 4th decision. Root cause: Claude's `extract` decision put
the observed balance text directly into the tool's `output` field instead of providing a
`strategy`/`value` locator — because neither `ACTION_TOOL`'s schema nor `SYSTEM_PROMPT` in
`agent/discovery.py` ever said `output` was a field *name*, not the data value. Fixed by adding
field descriptions to the tool schema, clarifying the system prompt, and adding a defensive
`RuntimeError` (with the full decision payload) if `strategy` is ever missing, instead of an
opaque `KeyError`. Evidence: `evidence/runs/1b835d17-.../events.jsonl` (steps 0-3 succeeded,
step 3's decision shows the malformed `output` value).

**Real defect #2 (not a crash, but a genuine artifact-quality bug) — diagnosed and fixed:** the
second attempt completed and produced a schema-valid artifact, but its `extract` step's locator
was `strategy=text, value="$4,250.25"` — the literal balance for member 10001. This can never
generalize to another member. Root cause: `PlaywrightSurface.observe()` only exposes the
accessibility tree (roles/text/labels, never CSS/DOM structure), and the discovery tool schema
never offered `xpath` as a strategy option even though `Locator`/`PlaywrightSurface` already
support it — so Claude had no way to express "the cell next to the stable label" instead of "the
value I see." Fixed by adding `xpath` to the strategy enum and prompting Claude to reference a
stable sibling row-label instead of the volatile value. Also fixed `_enrich_errors` in the same
file, which only attached the `MEMBER_NOT_FOUND` rule to the last step — meaning a not-found
member would fail at "click Open Accounts" (which doesn't exist on that page) instead of
short-circuiting to a business outcome; now attached to every step after the first. Evidence:
`evidence/runs/aceafd67-.../artifact.json` (flawed) vs. `evidence/runs/8dcc3190-.../artifact.json`
(fixed, `xpath` locator).

**Real gap #3 — discovery accepted completion without verifying its own checkpoint:** the
`complete` branch only checked that something had been extracted, never that the declared
success checkpoint (the "Savings Account" heading) was actually visible. Fixed by moving
`success_target`'s construction before the loop and asserting `await surface.visible(success_target)`
before accepting `complete`, emitting a `discovery.checkpoint_verified` evidence event.

**Files changed in this phase:**
- `src/capability_platform/agent/discovery.py` — all three fixes above (schema/prompt clarity,
  checkpoint-before-completion, generalizable locators + error-rule attachment).
- `artifacts/lookup-member-savings-balance.v1.json` — regenerated by genuine discovery (this was
  always the intent: the original file's own `discovered_by` field said "example; regenerate
  with Claude using the discover command").
- `tests/test_replay_e2e.py` — one test's hardcoded assumption of the old artifact's step ID
  (`"enter-member"`) replaced with a dynamic read of `artifact.steps[0].id`, since the artifact
  is now genuinely discovery-generated and uses generic `step-N` IDs.
- `evidence/README.md` — full discovery + post-discovery replay documentation, including the
  real failure and both diagnosed defects.
- No changes to `computer_use/replay.py`, `demo_app/app.py`, or any policy/redaction code —
  this phase was discovery-side only, per CLAUDE.md rule 4 (replay stays LLM-free).

**Requirement checklist:**
| # | Requirement | Result |
|---|---|---|
| 1 | Use the configured key without printing/logging it | PASS — grepped the full repo (excluding `.env`) for the raw key value: no matches |
| 2 | Real observe-decide-act loop | PASS — 4 real `messages.create` rounds in the successful run, visible in `events.jsonl` |
| 3 | Browser observations treated as untrusted data | PASS — model is constrained to a fixed action enum via forced tool-use; page text is never executed as instructions |
| 4 | Extraction + checkpoint verification before completion | **Was missing — fixed.** `complete` now asserts the success checkpoint is visible |
| 5 | Compile trace into typed artifact | PASS — `CapabilityArtifact` construction (which validates on init) |
| 6 | Parameterize member number as `{{memberId}}` | PASS — `step-1.value == "{{memberId}}"` |
| 7 | Don't persist the model transcript as the capability | PASS — `artifact.json` has no transcript/chat history, only typed steps |
| 8 | No API key/credential/cookie/raw sensitive data in the artifact | PASS — manual inspection + grep |
| 9 | Save redacted discovery evidence | PASS — all events pass through the same `Redactor` used elsewhere |
| 10 | Validate generated artifact using `CapabilityArtifact` | PASS — `uv run capability-platform list` (uses `ArtifactStore.list()` → `CapabilityArtifact.model_validate`) |
| 11 | Replay generated artifact for member 10002, no LLM | PASS — `c5c43265-...`: `status=success`, `savingsBalance=1220.0` |
| 12 | Update TASKS.md | This section |

**Full suite after all fixes:** `10 passed` (`uv run pytest -q -v`). **Lint:** `All checks
passed!`. No fabricated evidence — both real failures above are preserved in `evidence/runs/`
alongside the eventual successful runs.

## Phase 4b log — user-reported failure, diagnosed and fixed (real Anthropic API calls)

The user ran `uv run capability-platform discover --goal "Find member 10001 and return the
current savings balance" --member-id 10001` themselves and hit a real error (a slightly
reworded goal, no trailing period, but functionally the same task). Reproduced directly:

```
LookupError: role:Search matched 0
  File ".../computer_use/surface.py", line 68, in resolve
```

**Diagnosed:** `evidence/runs/4bb650a8-.../events.jsonl` shows Claude's decision was
`{"strategy": "role", "name": "button", "value": "Search"}` — it swapped `value` and `name`.
For `strategy="role"`, `PlaywrightSurface._locator()` uses `value` as the ARIA role type and
`name` as the accessible label (`page.get_by_role(locator.value, name=locator.name)`), but
`ACTION_TOOL`'s field descriptions (added in Phase 4) explained `value` for text/css/xpath and
never said what it meant specifically for `role` — a real, reproducible prompt-clarity gap that
the earlier fix didn't fully close, distinct from the two Phase 4 defects.

**Fixed:** `agent/discovery.py` — `SYSTEM_PROMPT` now states explicitly, with a worked example,
that for `strategy='role'`, `value` is always the ARIA role type and `name` is always the
accessible label, and that they must never be swapped; `ACTION_TOOL`'s `value`/`name` field
descriptions were rewritten to state the same per-strategy rule directly in the schema (not
just the prompt), so the constraint is visible in two places.

**Re-validated for real** (same goal wording the user used): discovery succeeded
(`strategy=role, value=button, name=Search` — correct this time), the resulting artifact's
extract step again used the stable `xpath` locator, and `capability-platform replay
lookup-member-savings-balance.v1 --input memberId=10002` returned `status=success,
savingsBalance=1220.0`. Full suite: `10 passed`. Lint: `All checks passed!`.

**No code changes outside `agent/discovery.py`.** This is a good illustration of why LLM-driven
discovery is non-deterministic run to run (the same prompt can still produce a different, valid
tool-call shape) — it's also exactly why the project's core invariant compiles discovery output
into a fixed, reviewable artifact rather than re-invoking the model on every replay.

## Headline blocker — RESOLVED as of Phase 4

**Originally:** `evidence/` contained only `evidence/README.md` — no discovery-run trace, no
replay-run trace, no committed artifact, and `.gitignore` excluded `evidence/runs/` outright.
The PDF (Section 4) calls a genuine, evidenced discovery run **non-negotiable**. This is now
closed: `.gitignore`'s exclusion was removed (Phase 3), real replay evidence was captured
(Phase 3: success, business outcome, validation failure, hard failure), and a real Claude
discovery run now exists with committed evidence, including two real diagnosed failures
preserved alongside the eventual success (Phase 4). See the Phase 4 log above and T1/T8/T12/T15
below.

---

### T1 — Goal-driven observe/decide/act loop
- **PDF requirement (§3.1):** "Run an LLM-driven observe → decide → act loop against a live surface until the goal is met or a stopping condition is hit... The agent must actually interact with a real UI (click, type, navigate, read state)."
- **Classification:** Mandatory
- **Responsible module:** `src/capability_platform/agent/discovery.py`, `src/capability_platform/computer_use/surface.py`
- **Status:** Complete — **Phase 4 update:** run for real 3 times (1 real failure diagnosed and fixed, 1 flawed-but-successful run diagnosed and fixed, 1 fully successful and generalizable run). Evidence committed under `evidence/runs/{1b835d17,aceafd67,8dcc3190}-.../`. See Phase 4 log above.
- **Gap to close:** None remaining.
- **Validation command:** `uv run capability-platform discover --goal "Find member 10001 and return savings balance"`
- **Evidence required:** A committed discovery-run event log (`evidence/runs/.../events.jsonl` or equivalent) showing real `messages.create` round-trips and the resulting artifact file.

### T2 — Typed, versioned, reviewable artifact schema
- **PDF requirement (§3.2):** "Emit a typed, serializable artifact... ordered steps/actions, how each target element/control is identified (with your reasoning about robustness), typed input parameters, typed outputs/data to extract and their shape, a checkpoint or success condition... Design the schema deliberately; it's a focal point of the evaluation."
- **Classification:** Mandatory
- **Responsible module:** `src/capability_platform/models.py` (`CapabilityArtifact`, `Step`, `Target`, `Locator`, `Checkpoint`, `ParameterSpec`, `OutputSpec`)
- **Status:** Complete — every listed element is present: `Target.rationale` forces documented locator reasoning, `inputs`/`outputs` are typed with shape, `success: Checkpoint` is mandatory, `Step` validator enforces a `target` on click/type/select/extract.
- **Gap to close:** None required by the PDF. Optional hardening (not PDF-mandatory): `schema_version` is a hardcoded `Literal["1.0"]` with no migration path — REPORT.md's own "Cuts" section already acknowledges this as future work, which is an acceptable disclosure per the PDF's scope guidance.
- **Validation command:** `uv run pytest -q -m "not e2e" -k test_example_artifact_is_valid`
- **Evidence required:** `tests/test_models.py::test_example_artifact_is_valid` (passing), `artifacts/lookup-member-savings-balance.v1.json`.

### T3 — Deterministic replay with no LLM in the decision loop
- **PDF requirement (§3.3):** "Given a saved artifact and a set of input parameters, replay it without invoking the LLM for decisions... use stable element/control targeting, verify the checkpoint/success condition, and return any declared outputs."
- **Classification:** Mandatory
- **Responsible module:** `src/capability_platform/computer_use/replay.py`
- **Status:** Complete — traced the full `cli.py` → `runtime.py` → `ReplayEngine.execute` call path; zero LLM client instantiation or call anywhere in it. The only LLM footprint at all is an inert transitive `import anthropic` pulled in because `runtime.py` co-imports the discovery and replay factories in one module (no client object created, no key required, no network call on the replay path). **Phase 2 update:** confirmed live, not just by code review — `tests/test_replay_e2e.py::test_replay_success` passed against the real demo app on port 8001 (1 passed, 2.22s), and member 10001/10002/99999 states were independently verified by curl before the test ran.
- **Gap to close:** None required. Optional cleanup: split `runtime.py`'s discovery/replay factory imports so `replay`'s import graph has zero `anthropic` reference, for a stricter reading of CLAUDE.md rule 4.
- **Validation command:** `uv run pytest -q -m e2e` (requires `uv run uvicorn demo_app.app:app --port 8001` running); `grep -rn "anthropic\|openai\|OpenAI(\|Anthropic(" src/capability_platform/computer_use/replay.py` (expect no match)
- **Evidence required:** `tests/test_replay_e2e.py::test_replay_success` result; grep output showing no match.

### T4 — Three-way outcome taxonomy (business outcome / recoverable / hard failure)
- **PDF requirement (§3.3 + Glossary):** "Distinguish, in your result contract, between: expected business outcomes... recoverable conditions (e.g. dismiss a known interstitial, wait/retry a transient load), and hard failures that should stop and surface a clear, debuggable error." Glossary: "Conflating [business outcome and failure] is the most common design mistake here."
- **Classification:** Mandatory
- **Responsible module:** `src/capability_platform/models.py` (`RunStatus`, `ErrorCategory`), `src/capability_platform/computer_use/replay.py`
- **Status:** Partial — business outcome vs. hard failure is correctly separated and tested (`RunStatus.BUSINESS_OUTCOME` short-circuits before the generic exception handlers). But the "recoverable condition" leg is not demonstrably wired: `ErrorCategory.RECOVERABLE` is defined (`models.py`) but never assigned anywhere in `replay.py` (`grep -rn "RECOVERABLE" src/ tests/` matches only its own definition) — dead enum member. `RunStatus.PAUSED` is likewise defined but never assigned in `replay.py:69-183`; a live pause is signaled only by a non-null `intervention_id` on a result whose `status` field is left at its `FAILURE` default until the run completes.
- **Gap to close:**
  1. Implement the `"retry"` branch of `ErrorRule.recovery` in `replay.py` (the field already accepts `"retry"` but the executor's `if error_rule.recovery == "pause": ... raise RuntimeError(...)` has no `"retry"` branch) — on match, wait/retry the checkpoint a bounded number of times, tagging the outcome as `ErrorCategory.RECOVERABLE` before falling through to hard failure if retries are exhausted.
  2. Set `result.status = RunStatus.PAUSED` when a run enters `interventions.wait_for_resume`, so the status field (not just `intervention_id`) reflects the paused state while blocked.
  3. Add an error rule of each kind (`retry`, `pause`) to a test artifact so both paths are exercised, not just declared.
- **Validation command:** `grep -n "RunStatus.PAUSED\|ErrorCategory.RECOVERABLE\|recovery == \"retry\"" src/capability_platform/computer_use/replay.py`
- **Evidence required:** New test(s) exercising a `"retry"`-recovery error rule and a `"pause"`-recovery rule, asserting the correct `RunStatus`/`ErrorCategory` values.

### T5 — Configurable allowlist actually enforced from config
- **PDF requirement (§3.4):** "Enforce an explicit, configurable allowlist (e.g. permitted domains/routes, and which action types are allowed). The agent must not act outside it."
- **Classification:** Mandatory
- **Responsible module:** `src/capability_platform/policy/engine.py`, `config/policy.json`
- **Status:** Partial — the allowlist is enforced and tested, but `config/policy.json` is **never read by any runtime code** (`grep -rn "policy.json\|config/policy" src/` returns nothing); `default_policy()` in `policy/engine.py` hardcodes an equivalent `Policy` dataclass directly in Python. Today the two happen to agree, but they are two separately maintained sources of truth with no mechanical link.
- **Gap to close:** Load `Policy` from `config/policy.json` in `default_policy()` (or wherever the engine is constructed) instead of duplicating it in Python literals, so the file is actually load-bearing rather than decorative.
- **Validation command:** `grep -rn "policy.json" src/capability_platform/` (currently returns nothing — should return the loader after the fix)
- **Evidence required:** A test asserting that editing `config/policy.json` changes `PolicyEngine` behavior.

### T6 — Safe vs. risky/irreversible action handling
- **PDF requirement (§3.4):** "Distinguish 'safe/reversible' actions from risky/irreversible ones, and handle the risky class conservatively (block, require confirmation, or flag — your call, justify it)."
- **Classification:** Mandatory
- **Responsible module:** `src/capability_platform/policy/engine.py`
- **Status:** Partial — `RiskLevel` (read_only/reversible/risky/irreversible) exists and `authorize_step` blocks anything above `maxRiskWithoutApproval` unless `approved=True`. However, `approved` is never passed as `True` by any call site (`replay.py:80` and `discovery.py:146` both call `authorize_step(step)` with the default `approved=False`) — risky/irreversible steps are unconditionally blocked today, with no confirmation flow wired up at all.
- **Gap to close:** Either (a) explicitly document "block" as the deliberate chosen conservative handling in REPORT.md §6 (a legitimate, PDF-sanctioned choice), or (b) wire an approval flow — plausibly through the existing intervention/handoff mechanism — that can set `approved=True` for a risky step after human sign-off.
- **Validation command:** `grep -rn "authorize_step(" src/capability_platform/` (check every call site's `approved` argument)
- **Evidence required:** REPORT.md §6 statement confirming "block" is the intended behavior, or a new test demonstrating an approved risky step executing.

### T7 — No secrets/raw PII persisted; redaction
- **PDF requirement (§3.4):** "Never persist secrets or raw sensitive data (credentials, tokens, full PII) into artifacts or logs. Redact appropriately."
- **Classification:** Mandatory
- **Responsible module:** `src/capability_platform/observability/evidence.py` (`Redactor`)
- **Status:** Partial — `Redactor` covers SSN, `authorization` header, and `api_key` patterns, applied to every `evidence.event(...)` JSON payload. Gaps: (1) `EvidenceCollector.screenshot()` writes a raw PNG with no redaction at all; (2) `config/policy.json`'s own `dataPolicy.neverPersist` list includes `sessionCookies`, but no `Redactor` pattern matches cookie strings; (3) only 2 of the 3 existing patterns (SSN, authorization) are unit-tested — `api_key` is untested.
- **Gap to close:** Add a redaction pattern for cookie/session-token shapes; add a test for the existing `api_key` pattern; document the screenshot-redaction gap explicitly in REPORT.md §6 as an accepted limitation (synthetic-data-only POC) if it's staying as-is.
- **Validation command:** `uv run pytest -q -m "not e2e" -k test_redacts_sensitive_values`
- **Evidence required:** `tests/test_redaction.py` extended to cover `api_key` and cookies.

### T8 — Structured log + richer failure signal
- **PDF requirement (§3.5):** "Produce enough evidence to understand and debug a run: a structured log of what the agent did and why, and at least one richer signal on failure (screenshot, DOM snapshot, trace, etc.)."
- **Classification:** Mandatory
- **Responsible module:** `src/capability_platform/observability/evidence.py`
- **Status:** Complete — **Phase 4 update:** discovery-side evidence now exists too (3 real discovery runs, including a genuine failure and its diagnosis), closing the other half of this requirement.
- **Gap to close:** None remaining.
- **Validation command:** `uv run capability-platform replay lookup-member-savings-balance.v1 --input memberId=10002` then inspect `evidence/runs/<run_id>/events.jsonl`
- **Evidence required:** Committed `events.jsonl` + at least one screenshot from a failure/business-outcome run.

### T9 — Detect stuck state, route intervention with context
- **PDF requirement (§3.6):** "Identify a stuck/blocked state and raise an intervention request to a human operator, carrying enough context to act on it (which capability/goal, the current step, the current state or screenshot, and why it stopped)."
- **Classification:** Mandatory
- **Responsible module:** `src/capability_platform/intervention/manager.py`, `src/capability_platform/computer_use/replay.py:119-131`
- **Status:** Complete — a `"pause"`-recovery error rule triggers `interventions.create(run_id, error_rule.message, step_id, screenshot, state=await surface.observe())`, carrying run/step/reason/screenshot/accessibility-state, exactly per the requirement.
- **Gap to close:** None for the mechanism itself; see T10 for the missing demonstration.
- **Validation command:** `grep -n "interventions.create" src/capability_platform/computer_use/replay.py`
- **Evidence required:** Code citation above (mechanism exists); see T10 for a working demonstration.

### T10 — Human takes control of the live session, hands back, actions recorded
- **PDF requirement (§3.6):** "Let the human operate the same live session the automation was using — not a fresh one — perform the manual steps, and then hand control back so the run can resume or complete. Preserve context and evidence across the handoff, and record what the human did." Evaluation criterion #4: "A real, well-reasoned mechanism... not just a TODO."
- **Classification:** Mandatory (operator UI may be mocked per §3.6's explicit scope note)
- **Responsible module:** `src/capability_platform/intervention/manager.py`, `src/capability_platform/api/app.py` (`/interventions`, `/interventions/{id}/resume`)
- **Status:** Partial — the mechanism is real: `wait_for_resume` blocks the same coroutine on an `asyncio.Event` while the live `PlaywrightSurface`/`Page` stays open (browser never closed/reopened), `resume()` flips ownership and unblocks, and `replay.py` `continue`s the **same** step loop afterward — genuinely same-session. However: (1) **zero test coverage** — no test touches `intervention/manager.py` or exercises the `"pause"` path; (2) the shipped example artifact has no `"pause"`-recovery error rule, so the documented demo path never exercises this; (3) no evidence in `/evidence/` shows a captured handoff.
- **Gap to close:** Add a second artifact (or a variant input) whose error rule uses `"pause"` recovery, add a test that drives a pause → `POST /interventions/{id}/resume` → completion cycle, and capture that run's evidence under `evidence/`.
- **Validation command:** New test, e.g. `tests/test_intervention.py::test_pause_and_resume`; `curl -X POST localhost:8000/interventions/{id}/resume`
- **Evidence required:** Passing new test; committed intervention screenshot + `control.transferred` events in evidence log.

### T11 — Design (not build) for heterogeneous surfaces & multi-tenant reuse
- **PDF requirement (§3.7, explicitly "design, not necessarily build"):** "How your artifact schema and replay engine would extend from your chosen surface to a legacy web app and/or a desktop app... How would you represent an artifact so it can be reused... across tenants... How do you detect and manage per-tenant/version drift?"
- **Classification:** Mandatory, design only (PDF: "We don't expect you to implement multi-tenant or desktop support.")
- **Responsible module:** `REPORT.md` §4 ("Heterogeneity & multi-tenant"), `models.py` (`ApplicationBinding`, tenant overrides)
- **Status:** Complete — REPORT.md §4 addresses `SurfaceAdapter` as the seam, vendor/product/version binding, tenant overrides, fingerprinting for compatible-variant selection, and failing closed on drift. See T18 for a concrete code-level caveat that weakens this narrative's credibility.
- **Gap to close:** None required by the PDF. Recommended: once T18 is fixed, this section's claim becomes fully backed by code.
- **Validation command:** Manual read of `REPORT.md` §4.
- **Evidence required:** REPORT.md §4 text (present).

### T12 — "The discovery run has to be real," with evidence
- **PDF requirement (§4, non-negotiable):** "One thing that isn't your call: the discovery run has to be real. At least one genuine LLM-driven run against a live surface, with the evidence in `/evidence/` to show it happened."
- **Classification:** Mandatory, explicitly non-negotiable
- **Responsible module:** `evidence/`, `.gitignore`, `scripts/capture_evidence.sh`
- **Status:** Complete — **Phase 4 update:** a real discovery run's evidence (including a genuinely diagnosed failure) is now committed alongside the Phase 3 replay evidence. Both halves of this non-negotiable requirement are satisfied.
- **Gap to close:** None remaining.
- **Validation command:** `cat .gitignore`; `uv run capability-platform discover --goal "..."`; `find evidence -type f`
- **Evidence required:** Committed files under `evidence/runs/` (or equivalent) containing a real discovery trace and a real replay trace.

### T13 — `/README.md`: setup + exact demo commands
- **PDF requirement (§6.1):** "how to set up and run it... a demo path: the exact command(s) to run the agent on a goal, then replay the resulting artifact."
- **Classification:** Mandatory, exact path
- **Responsible module:** `README.md`
- **Status:** Complete — setup (`.env`, `make install`), demo path (`make demo`, `make discover`, `make replay` / explicit `uv run capability-platform replay ...` commands with expected outputs) are all present and specific.
- **Gap to close:** None for PDF compliance. See T17 for a separate, non-PDF gap (OpenAI mention/default model).
- **Validation command:** Manual read of `README.md`.
- **Evidence required:** README.md contents (present).

### T14 — `/REPORT.md`: exact 7 headings
- **PDF requirement (§6.2, verbatim):** "1. Architecture — ... 2. Artifact schema — ... 3. Determinism & error handling — ... 4. Heterogeneity & multi-tenant — ... 5. Escalation & handoff — ... 6. Safety — ... 7. Cuts — ..."
- **Classification:** Mandatory, exact path + exact headings
- **Responsible module:** `REPORT.md`
- **Status:** Complete — verified verbatim, in order: "## 1. Architecture", "## 2. Artifact schema", "## 3. Determinism & error handling", "## 4. Heterogeneity & multi-tenant", "## 5. Escalation & handoff", "## 6. Safety", "## 7. Cuts". Exact match to the PDF's required heading list and order.
- **Gap to close:** None.
- **Validation command:** `grep -n "^## " REPORT.md`
- **Evidence required:** Grep output (7 lines, matching headings above).

### T15 — `/evidence/`: discovery + replay + one error-case replay
- **PDF requirement (§6.3):** "A demonstration of the end-to-end flow in `/evidence/`... a saved example artifact plus logs from both a discovery run and a replay run. Ideally include one replay that hits an error or exceptional state."
- **Classification:** Mandatory, exact path
- **Responsible module:** `evidence/`
- **Status:** Complete — **Phase 4 update:** the discovery-run half is now also satisfied. `evidence/` contains a real discovery trace (`8dcc3190-...`), the generated artifact, replay traces for success/business-outcome/validation-failure/hard-failure, and — as a bonus beyond "ideally" — a genuinely diagnosed discovery failure.
- **Gap to close:** None remaining.
- **Validation command:** `uv run capability-platform replay lookup-member-savings-balance.v1 --input memberId=99999`
- **Evidence required:** Committed replay log showing `RunStatus.BUSINESS_OUTCOME` / `MEMBER_NOT_FOUND`.

### T16 — Evaluation anti-goal: avoid over-building infrastructure
- **PDF requirement (§7, verbatim):** "We do not reward feature breadth, framework name-dropping, or building scaling infrastructure (queues, clusters, multi-tenant plumbing)... A small, correct, well-argued system is the goal."
- **Classification:** Advisory / risk, not a defect
- **Responsible module:** REST API (`api/app.py`), MCP server (`mcp/server.py`), embeddings/reranking (`capabilities/registry.py`), synthesis (`synthesis/result.py`) — all real, working, but not PDF-mandated
- **Status:** Flag — this is real, functioning, minimal code (not vaporware), and REPORT.md §7 ("Cuts") does explicitly list these as deliberate scope choices, which mitigates the risk. But per the PDF's anti-goal, this breadth isn't itself credited, and several load-bearing pieces the rubric weights most heavily (T4, T6, T10) are only Partial — concrete evidence that effort may have skewed toward secondary features.
- **Gap to close:** None mandatory. Recommendation: prioritize closing T4/T6/T10/T12 before investing further in REST/MCP/embeddings polish.
- **Validation command:** N/A (judgment call).
- **Evidence required:** REPORT.md §7 "Cuts" section (present, partially addresses this).

### T17 — Default discovery model: OpenAI GPT-5 mini (user-directed, not a PDF requirement)
- **Requirement source:** Stated project direction: "The application's default runtime discovery model will be OpenAI GPT-5 mini, with Anthropic Claude retained as an optional provider." The PDF leaves LLM provider entirely to the candidate's judgment (§4), so this is not a PDF compliance gap — it's a separate, explicitly stated direction for future work.
- **Classification:** Non-PDF / project direction
- **Responsible module:** `src/capability_platform/settings.py`, `src/capability_platform/agent/discovery.py`, `pyproject.toml`, `README.md`
- **Status:** Missing entirely — zero `openai` dependency in `pyproject.toml`, zero `openai`/`gpt-5` mentions anywhere in the repo. `settings.py` only has `anthropic_api_key`/`claude_model`; `discovery.py` hardcodes `AsyncAnthropic`.
- **Gap to close:** Add an `openai` dependency and an `OpenAIDiscoveryAgent` (or provider-parameterized `ClaudeDiscoveryAgent`) implementing the same discovery-loop interface, default `settings.py` to it (`discovery_model_provider = "openai"`, `openai_model = "gpt-5-mini"`), keep `AsyncAnthropic` path fully functional and selectable via config/env, and update README/`.env.example` accordingly. Discovery-only change — must not touch `computer_use/replay.py` (replay stays LLM-free per CLAUDE.md rule 4).
- **Validation command:** `grep -rniI "openai\|gpt-5" .` (currently empty — should show the new provider code after the fix)
- **Evidence required:** A discovery run executed with the OpenAI provider (evidence committed per T12), plus a test/inspection confirming `replay.py` still has no LLM dependency after the change.

### T18 — CLAUDE.md rule 8: surface-specific behavior stays behind `SurfaceAdapter`
- **Requirement source:** CLAUDE.md architecture rule 8 (project-internal, but the PDF's §3.7 "surface abstraction" design goal depends on this seam actually existing in code for the REPORT.md §4 narrative to be credible).
- **Classification:** Internal architecture rule
- **Responsible module:** `src/capability_platform/computer_use/surface.py` (`SurfaceAdapter` Protocol, `PlaywrightSurface`), `src/capability_platform/computer_use/replay.py`
- **Status:** Partial / violated in practice — `SurfaceAdapter` Protocol declares only `observe`/`click`/`type`/`extract`, but `ReplayEngine` (a) type-hints and constructs the concrete `PlaywrightSurface` directly (`replay.py:66`), not the Protocol; (b) reaches through to raw Playwright `Page` methods not on the Protocol at all for `NAVIGATE` (`surface.page.goto(url)`, line 92) and `WAIT` (`surface.page.wait_for_timeout(...)`, line 99) actions, and for URL/value checkpoints (`surface.page.url`, `surface.resolve(...)`, lines 42-51). A desktop/AX or legacy-web adapter could not be substituted today without rewriting `ReplayEngine` itself.
- **Gap to close:** Extend `SurfaceAdapter` to declare `navigate`, `wait`, and checkpoint-relevant methods (or a `resolve`/`current_url` primitive), and have `ReplayEngine` depend only on that Protocol type, injected rather than constructed inline.
- **Validation command:** `grep -n "surface\.page\.\|PlaywrightSurface(" src/capability_platform/computer_use/replay.py`
- **Evidence required:** Grep output above (currently shows 3+ direct `Page`-level accesses that should be zero post-fix).

### T19 — CLAUDE.md: normalize capability sources, no source-specific planner branches
- **Requirement source:** CLAUDE.md: "When adding a capability source, normalize it into `CapabilityDescriptor`... Do not add source-specific branches to the planner."
- **Classification:** Internal architecture rule
- **Responsible module:** `src/capability_platform/capabilities/registry.py`
- **Status:** Complete — `CapabilityRegistry.search()` scores every candidate uniformly via `_embedding`/`_cosine`/`reliability`/`trust`, branching only on `capability.trust` (a normalized field on `CapabilityDescriptor`), never on `capability.source`.
- **Gap to close:** None.
- **Validation command:** `grep -n "\.source" src/capability_platform/capabilities/registry.py` (no branching found)
- **Evidence required:** Code citation above; `tests/test_models.py::test_semantic_registry_prefers_balance_capability`.

### T21 — Learned capabilities exposed through REST and MCP
- **Requirement source:** Stated platform goal (session instructions): "Learned capabilities are exposed through REST and MCP." (The PDF's closest match is stretch goal §8.1, "agent-facing capability interface" — see T16 for the associated over-building risk; this task tracks whether the exposure itself works, independent of that risk.)
- **Classification:** Stated goal (stretch per PDF, core per session instructions)
- **Responsible module:** `src/capability_platform/api/app.py` (REST), `src/capability_platform/mcp/server.py` (MCP)
- **Status:** Complete — REST: `GET /capabilities` (list), `POST /capabilities/{id}/execute` (invoke via deterministic `ReplayEngine`, no LLM), `POST /discover`, `GET`/`POST /interventions*`. MCP: a real `FastMCP` server exposing `list_capabilities()` and `lookup_member_savings_balance(member_id)`, the latter also routing through `ReplayEngine` (confirmed no LLM on this path), registered in `.mcp.json` for stdio transport. Both surfaces call the same deterministic replay path, not a duplicate execution engine.
- **Gap to close:** None functionally. Recommended: add a REST/MCP invocation to the evidence bundle (T12/T15) so "invoked by name with typed args" is demonstrated end-to-end, not just unit-level.
- **Validation command:** `uv run uvicorn capability_platform.api.app:app --port 8000` then `curl localhost:8000/capabilities`; `uv run python -m capability_platform.mcp.server` (stdio)
- **Evidence required:** A committed REST or MCP invocation trace showing a capability executed via one of these surfaces.

### T22 — Clear separation of tools/skills/embeddings/retrieval/reranking/policy/synthesis
- **Requirement source:** Stated platform goal (session instructions): "Tools, skills, embeddings, capability retrieval, reranking, policy, and grounded synthesis remain clearly separated."
- **Classification:** Stated goal / architecture check
- **Responsible module:** `capabilities/registry.py` (embeddings + retrieval + reranking), `policy/engine.py` (policy), `synthesis/result.py` (synthesis), `skills/member_financial_summary.py` (skills), `mcp/server.py` + `api/app.py` (tool/capability exposure)
- **Status:** Complete — each concern lives in its own module with no cross-imports blurring boundaries: `registry.py`'s `_embedding`/`_cosine`/`search` (dependency-free hashing embeddings + linear-weighted rerank on trust/reliability) has no policy or synthesis logic in it; `PolicyEngine.authorize_step`/`authorize_url` are pure gate functions called by `replay.py`/`discovery.py`, not by the registry; `GroundedSynthesizer.synthesize` only formats `ExecutionResult` fields post-hoc, with no access to the registry or policy; `MemberFinancialSummarySkill` composes over a `CapabilityInvoker` protocol rather than reaching into `ReplayEngine`/`registry.py` internals directly. Confirmed via T19's check that `registry.py` has no source-specific or policy-specific branching.
- **Gap to close:** None.
- **Validation command:** `grep -rln "PolicyEngine\|GroundedSynthesizer" src/capability_platform/capabilities/registry.py` (expect no match, confirming registry doesn't reach into policy/synthesis)
- **Evidence required:** Grep output above; module tree already listed at the top of this assessment.

### T23 — Verify input parameters against the artifact contract before browser execution
- **Requirement source:** Phase 3 instructions, item 5 (a concrete instance of the PDF §3.3 mandate to detect "a validation error" as one of the named runtime conditions, alongside "record not found," a permission denial, etc.). **Not caught during the Phase 1 assessment** — this gap existed in the code the whole time but wasn't flagged as its own task until Phase 3 execution surfaced it.
- **Classification:** Mandatory (PDF §3.3, implied by the named "validation error" example)
- **Responsible module:** `src/capability_platform/models.py` (`ErrorCategory.VALIDATION`), `src/capability_platform/computer_use/replay.py` (`ReplayEngine._validate_inputs`)
- **Status:** Complete (fixed in Phase 3) — `_validate_inputs` checks every `ParameterSpec.required`/`.pattern` before `PlaywrightSurface` is constructed; a failure short-circuits with `RunError(category=VALIDATION, code="MISSING_INPUT"|"INVALID_INPUT")` and never opens a browser.
- **Gap to close:** None remaining.
- **Validation command:** `uv run pytest -q -m "not e2e" -k test_replay_validation`
- **Evidence required:** `tests/test_replay_validation.py` (2 tests, passing); real CLI run `e97ff371-56e1-4e5f-bfde-5386983d8e5e` under `evidence/runs/` showing `status=failure`/`error.category=validation` with no screenshot (proving the browser was never touched).

### T24 — Discovery tool schema must disambiguate locator fields from data values
- **Requirement source:** Found during Phase 4's genuine discovery run, not caught by prior code review. Relates to PDF §3.2 ("how each target element/control is identified, with your reasoning about robustness").
- **Classification:** Bug (discovery-side only)
- **Responsible module:** `src/capability_platform/agent/discovery.py` (`SYSTEM_PROMPT`, `ACTION_TOOL`)
- **Status:** Complete (fixed) — the tool schema now documents every field's purpose (`output` is explicitly "the NAME to store the result under... never the extracted value itself"), and a defensive `RuntimeError` replaces an opaque `KeyError` if a decision is missing a required locator.
- **Gap to close:** None remaining.
- **Validation command:** `grep -n "description" src/capability_platform/agent/discovery.py`
- **Evidence required:** `evidence/runs/1b835d17-.../events.jsonl` (the original crash, preserved) vs. a clean run afterward.

### T25 — Discovery must verify its own success checkpoint before accepting completion
- **Requirement source:** Phase 4 instructions, item 4, and implicitly PDF §3.2 ("a checkpoint or success condition").
- **Classification:** Bug (discovery-side only)
- **Responsible module:** `src/capability_platform/agent/discovery.py` (`discover()`)
- **Status:** Complete (fixed) — `complete` now asserts `await surface.visible(success_target)` before accepting completion, emitting `discovery.checkpoint_verified`. Previously only "was something extracted?" was checked.
- **Gap to close:** None remaining.
- **Validation command:** `grep -n "checkpoint_verified\|surface.visible(success_target)" src/capability_platform/agent/discovery.py`
- **Evidence required:** `discovery.checkpoint_verified` event in `evidence/runs/8dcc3190-.../events.jsonl`.

### T26 — Discovery-generated locators must generalize across inputs, not overfit to the example
- **Requirement source:** Found during Phase 4's genuine discovery run. Directly relevant to PDF §3.2's "reasoning about robustness" and the evaluation criterion "sound locator, wait, and checkpoint strategy."
- **Classification:** Bug (discovery-side only)
- **Responsible module:** `src/capability_platform/agent/discovery.py` (`ACTION_TOOL`, `SYSTEM_PROMPT`, `_enrich_errors`)
- **Status:** Complete (fixed) — added `xpath` as a locator strategy option (already supported by `Locator`/`PlaywrightSurface`, just never offered to the model), prompted Claude to reference a stable sibling label instead of the volatile value being extracted, and fixed `_enrich_errors` to attach the business-outcome rule to every step after the first instead of only the last. Verified by replaying the resulting artifact (discovered against member 10001) for member 10002 — a different input than it was discovered with — with a matching success result.
- **Gap to close:** None remaining, though this is a narrow, demo-specific heuristic (`_enrich_errors` still hardcodes the "Member not found" text and always attaches to "all steps after the first") — a more general capability-agnostic version would need a broader design, out of scope for this single-capability POC.
- **Validation command:** `uv run capability-platform replay lookup-member-savings-balance.v1 --input memberId=10002` (using the artifact discovered against member 10001)
- **Evidence required:** `evidence/runs/c5c43265-.../` (`status=success`, `savingsBalance=1220.0`, different member than discovery used).

### T27 — The example artifact was never actually tracked in git
- **Requirement source:** PDF §6.3 requires "a saved example artifact" as part of the `/evidence/` deliverable. Found during Phase 4 while checking `git status` after regenerating the artifact via discovery — not caught in any prior phase.
- **Classification:** Repo-integrity bug (not a PDF violation of intent, but would silently break the submission)
- **Responsible module:** `.gitignore`, `artifacts/lookup-member-savings-balance.v1.json`
- **Status:** Complete (fixed) — `git ls-files artifacts/` showed only `.gitkeep` was ever tracked; `artifacts/*.json` in `.gitignore` had silently excluded the example artifact from every commit since the repo's initial commit, including the hand-crafted example that shipped originally. A fresh `git clone` of this repo at any prior point would have been missing the one artifact every test, the README's demo path, and the CLI's `replay` command all depend on. Fixed by whitelisting this specific file in `.gitignore` (`!artifacts/lookup-member-savings-balance.v1.json`), matching the pattern already used for `.gitkeep`.
- **Gap to close:** None remaining, but the file must actually be `git add`ed and committed (not done automatically in this session, per the instruction not to commit without being asked).
- **Validation command:** `git ls-files artifacts/` (should list both `.gitkeep` and the artifact json after staging)
- **Evidence required:** `git status` showing the artifact as untracked-but-includable rather than ignored (confirmed).

### T20 — Test/lint baseline (process check per assessment instructions)
- **Requirement source:** Assessment instructions, step 12.
- **Classification:** Process
- **Responsible module:** whole repo
- **Status:** Complete — both commands pass cleanly when run sequentially (see "Baseline commands run" above). **Phase 2 update:** full suite including the e2e test now passes live (5 passed, 0.45s) with the demo app running on port 8001. Test coverage is still thin (5 test functions total across 3 files) relative to the number of Partial/Missing items above — none of `intervention/manager.py`, `policy/engine.py`'s risk-approval path, or the `"retry"`/`"pause"` recovery branches in `replay.py` have dedicated tests.
- **Gap to close:** N/A for pass/fail; new tests listed under T4, T6, T7, T10 close the coverage gap.
- **Validation command:** `uv run pytest -q -m "not e2e"` then `uv run ruff check .` (run sequentially, not in parallel)
- **Evidence required:** Command output above (captured in this file).

---

## Summary

| Status | Count | IDs |
|---|---|---|
| Complete | 19 | T1, T2, T3, T8, T9, T11, T12, T13, T14, T15, T19, T20, T21, T22, T23, T24, T25, T26, T27 |
| Partial | 7 | T4, T5, T6, T7, T10, T16 (advisory), T18 |
| Missing | 1 | T17 |
| Unverified | 0 | — |

**Recommended implementation order** (each item closes a gap identified above; none requires
architectural changes — all extend the existing design). The evidence blocker (formerly the top
priority) is now fully closed as of Phase 4:

1. **T4** — wire up the `"retry"` recovery branch and `RunStatus.PAUSED`, and add tests exercising both the recoverable and paused paths. Closes the taxonomy gap the PDF glossary calls "the most common design mistake."
2. **T10** — add a pause-triggering artifact/test and capture its evidence, so the human-handoff mechanism is demonstrated, not just present in code.
3. **T5 / T6** — load `PolicyEngine` from `config/policy.json`, and either document "block" as final for risky actions or wire an approval path.
4. **T7** — add cookie/session redaction pattern and the missing `api_key` test.
5. **T18** — extend `SurfaceAdapter` so `ReplayEngine` no longer reaches into raw Playwright `Page` calls, backing up the REPORT.md §4 heterogeneity story with code.
6. **T17** — add OpenAI GPT-5 mini as the default discovery provider, Claude retained as optional, without touching replay's LLM-free guarantee.

No changes were made to source code, tests, configuration, or REPORT.md/README.md during this
assessment. This file is ready for review — implementation work will follow the order above
once you approve it.
