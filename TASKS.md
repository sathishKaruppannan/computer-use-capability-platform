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

## Headline blocker

**`evidence/` contains only `evidence/README.md`.** No discovery-run trace, no replay-run
trace, no error-case replay, no artifact copy exists anywhere in the repo. `.gitignore` line 9
excludes `evidence/runs/`, so even running `scripts/capture_evidence.sh` locally would never
produce evidence that lands in the committed repo as submitted. The PDF (Section 4) calls this
**non-negotiable**: *"the discovery run has to be real. At least one genuine LLM-driven run
against a live surface, with the evidence in `/evidence/` to show it happened. That's the heart
of the project and we can't assess a description of it."* Section 6.3 additionally requires
committed logs from **both** a discovery run and a replay run, ideally including one replay
that hits an error/exceptional state. This is currently the single highest-priority gap — see
T12/T15.

---

### T1 — Goal-driven observe/decide/act loop
- **PDF requirement (§3.1):** "Run an LLM-driven observe → decide → act loop against a live surface until the goal is met or a stopping condition is hit... The agent must actually interact with a real UI (click, type, navigate, read state)."
- **Classification:** Mandatory
- **Responsible module:** `src/capability_platform/agent/discovery.py`, `src/capability_platform/computer_use/surface.py`
- **Status:** Complete code / **Unverified at runtime** — `ClaudeDiscoveryAgent` implements a real observe→decide→act loop calling `AsyncAnthropic.messages.create` and driving `PlaywrightSurface`, but no committed evidence shows it has actually been run successfully (see headline blocker).
- **Gap to close:** Run `capability-platform discover` for real with a valid `ANTHROPIC_API_KEY` and commit the resulting trace under `evidence/`.
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
- **Status:** Complete — traced the full `cli.py` → `runtime.py` → `ReplayEngine.execute` call path; zero LLM client instantiation or call anywhere in it. The only LLM footprint at all is an inert transitive `import anthropic` pulled in because `runtime.py` co-imports the discovery and replay factories in one module (no client object created, no key required, no network call on the replay path).
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
- **Status:** Complete code / **Unverified at runtime** — `EvidenceCollector.event()` writes structured JSONL, `.screenshot()` captures PNGs on failure/pause; both are called at every meaningful point in `replay.py`/`discovery.py`. Same root cause as the headline blocker: no committed evidence exists to confirm this produces a usable trace end-to-end.
- **Gap to close:** Same as T12/T15 — produce and commit a real run's evidence.
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
- **Status:** Missing — `evidence/` contains only `README.md`; `.gitignore` excludes `evidence/runs/` so this can never be committed as currently configured. Top-priority blocker in this assessment.
- **Gap to close:** (1) Remove or scope down the `evidence/runs/` gitignore rule so at least one real run's output can be committed; (2) run `scripts/capture_evidence.sh` (or the underlying `discover`/`replay` commands) with a real `ANTHROPIC_API_KEY`; (3) commit the resulting discovery-run and replay-run evidence bundles.
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
- **Status:** Missing — same root cause as T12.
- **Gap to close:** Same as T12, plus specifically ensure one committed replay run demonstrates the `BUSINESS_OUTCOME` path (e.g. `memberId=99999` → `MEMBER_NOT_FOUND`, per README) as the "error/exceptional state" example.
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

### T20 — Test/lint baseline (process check per assessment instructions)
- **Requirement source:** Assessment instructions, step 12.
- **Classification:** Process
- **Responsible module:** whole repo
- **Status:** Complete — both commands pass cleanly when run sequentially (see "Baseline commands run" above). Test coverage is thin (5 test functions total across 3 files) relative to the number of Partial/Missing items above — none of `intervention/manager.py`, `policy/engine.py`'s risk-approval path, or the `"retry"`/`"pause"` recovery branches in `replay.py` have dedicated tests.
- **Gap to close:** N/A for pass/fail; new tests listed under T4, T6, T7, T10 close the coverage gap.
- **Validation command:** `uv run pytest -q -m "not e2e"` then `uv run ruff check .` (run sequentially, not in parallel)
- **Evidence required:** Command output above (captured in this file).

---

## Summary

| Status | Count | IDs |
|---|---|---|
| Complete | 10 | T2, T3, T9, T11, T13, T14, T19, T20, T21, T22 |
| Partial | 7 | T4, T5, T6, T7, T10, T16 (advisory), T18 |
| Missing | 3 | T12, T15, T17 |
| Unverified (runtime evidence only) | 2 | T1, T8 |

**Recommended implementation order** (each item closes a gap identified above; none requires
architectural changes — all extend the existing design):

1. **T12 / T15** — produce and commit real discovery-run and replay-run evidence (fix `.gitignore` first). This is the PDF's one explicitly non-negotiable requirement and currently the biggest risk.
2. **T4** — wire up the `"retry"` recovery branch and `RunStatus.PAUSED`, and add tests exercising both the recoverable and paused paths. Closes the taxonomy gap the PDF glossary calls "the most common design mistake."
3. **T10** — add a pause-triggering artifact/test and capture its evidence, so the human-handoff mechanism is demonstrated, not just present in code.
4. **T5 / T6** — load `PolicyEngine` from `config/policy.json`, and either document "block" as final for risky actions or wire an approval path.
5. **T7** — add cookie/session redaction pattern and the missing `api_key` test.
6. **T18** — extend `SurfaceAdapter` so `ReplayEngine` no longer reaches into raw Playwright `Page` calls, backing up the REPORT.md §4 heterogeneity story with code.
7. **T17** — add OpenAI GPT-5 mini as the default discovery provider, Claude retained as optional, without touching replay's LLM-free guarantee.

No changes were made to source code, tests, configuration, or REPORT.md/README.md during this
assessment. This file is ready for review — implementation work will follow the order above
once you approve it.
