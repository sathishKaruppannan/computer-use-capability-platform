# Requirements Traceability — PDF → Implementation

A personal reference map: every requirement in `docs/Assignment-Computer-Use-Automation-System.pdf`,
matched against exactly where it lives in the code, why it was built that way, and how to test
or debug it yourself. For the full phase-by-phase history (what broke, what was fixed, in what
order) see `TASKS.md`. For the actual evidence files, see `evidence/INDEX.md`. This document is
the "what and why," not the build log.

Each entry follows the same shape: **Requirement** (verbatim from the PDF) → **Where** (files) →
**How we achieved it** (the actual mechanism) → **Test it** (a command that proves it) →
**Debug it** (what to look at if it seems broken).

---

## §3.1 — Goal-driven agent loop

> "Run an LLM-driven observe → decide → act loop against a live surface until the goal is met or
> a stopping condition is hit (max steps, timeout, dead-end)."

**Where:** `src/capability_platform/agent/discovery.py` — `ClaudeDiscoveryAgent.discover()`
(the loop), `._decide()` (one LLM call per round).

**How we achieved it:** `discover()` runs `for index in range(self.max_steps):` — each iteration
calls `surface.observe()` (reads the live accessibility tree via Playwright), passes that plus
goal + history to `_decide()`, which forces Claude to return exactly one `browser_action` tool
call (`tool_choice={"type": "tool", "name": "browser_action"}`), then dispatches that action
(`click`/`type`/`extract`/`wait`/`complete`/`escalate`) against the real browser. Stops on
`complete` (with a checkpoint re-verification — see §3.2 below), `escalate` (raises), or
exhausting `max_discovery_steps` (default 20, raises).

**Test it:**
```bash
uv run uvicorn demo_app.app:app --port 8001 &          # terminal 1
uv run capability-platform discover --goal "Find member 10001 and return the current savings balance."
```
Requires `ANTHROPIC_API_KEY` in `.env` — this is the one requirement the PDF calls
non-negotiable to actually run for real (§4).

**Debug it:** every observe/decide/act round is logged to
`evidence/runs/<run_id>/events.jsonl` as `discovery.observed` / `discovery.decided` /
`discovery.acted` — read that file top to bottom to see exactly what Claude saw and chose at
each step. A crash mid-run leaves a `discovery-failure.png` screenshot in the same directory.

---

## §3.2 — Structured, typed artifact

> "Emit a typed, serializable artifact... ordered steps, how each target element is identified
> (with reasoning about robustness), typed inputs, typed outputs and shape, a checkpoint or
> success condition... versioned and reviewable."

**Where:** `src/capability_platform/models.py` — `CapabilityArtifact`, `Step`, `Target`,
`Locator`, `Checkpoint`, `ParameterSpec`, `OutputSpec`.

**How we achieved it:** every field the PDF names is a real, required Pydantic field, not
optional decoration — `Target.rationale` is mandatory (forces a written reason for every
locator choice), `Step`'s validator refuses to construct a `click`/`type`/`select`/`extract`
step without a `target`, `success: Checkpoint` is mandatory on the artifact, `inputs`/`outputs`
carry a declared `type` and `pattern`. `schema_version`/`version` give it a version identity;
`lifecycle` (`draft`→`approved`→...) makes it reviewable (see §3.4/T29 below — an unapproved
artifact can't be invoked by an agent).

Discovery also had to learn to make its own locators *robust*, not just present — two real bugs
were found and fixed here: an early run put the extracted *value itself* into the locator
(worked once, broke for every other input); the tool schema didn't disambiguate `role`
strategy's `value` (the ARIA type) from `name` (the label), so Claude occasionally swapped them.
Both fixed in the discovery prompt/schema, not by hand-editing artifact output.

**Test it:**
```bash
uv run pytest -q tests/test_models.py::test_example_artifact_is_valid
cat artifacts/lookup-member-savings-balance.v1.json   # read it yourself — steps, rationale, checkpoint
```

**Debug it:** `CapabilityArtifact.model_validate_json()` (in `ArtifactStore.load()`) raises a
Pydantic `ValidationError` with a precise field path if an artifact is malformed — that error
message tells you exactly which field is wrong.

---

## §3.3 — Deterministic replay, no LLM in the decision loop

> "Given a saved artifact and input parameters, replay it without invoking the LLM for
> decisions. This is the path an AI agent would trigger in production."

**Where:** `src/capability_platform/computer_use/replay.py` — `ReplayEngine.execute()`.

**How we achieved it:** `replay.py` has zero imports of `anthropic` or `openai` anywhere. It
walks `artifact.steps` in a fixed loop, resolving each declared locator and performing exactly
the declared action — no model call ever decides *what* to do next, only whether a declared
checkpoint/error condition currently holds.

**Test it:**
```bash
HEADLESS=true uv run capability-platform replay lookup-member-savings-balance.v1 --input memberId=10002
uv run pytest -q -m e2e tests/test_replay_e2e.py::test_replay_never_instantiates_llm_client
```
That last test is the strongest proof available: it monkeypatches `anthropic.AsyncAnthropic`/
`Anthropic` to **raise** if constructed, then runs a full replay to success — if replay ever
touched an LLM client, this test would fail loudly.

**Debug it:** `grep -rn "anthropic\|openai" src/capability_platform/computer_use/replay.py`
should return nothing. If a replay run behaves unexpectedly, `evidence/runs/<run_id>/events.jsonl`
has one `step.started`/`step.completed` pair per step — find where it stops progressing.

---

## §3.3 / Glossary — Outcome taxonomy (business outcome / recoverable / hard failure)

> "Distinguish: expected business outcomes... recoverable conditions (e.g. dismiss a known
> interstitial, wait/retry a transient load)... and hard failures." Glossary: "Conflating
> [business outcome and failure] is the most common design mistake here."

**Where:** `models.py` — `RunStatus` (`success`/`business_outcome`/`paused`/`failure`),
`ErrorCategory` (`business`/`recoverable`/`policy`/`validation`/`checkpoint_failed`/etc.);
dispatch logic in `replay.py`'s `execute()`.

**How we achieved it, one leg at a time:**
- **Business outcome** — an `ErrorRule(category=BUSINESS)` whose `when` checkpoint matches
  short-circuits to `RunStatus.BUSINESS_OUTCOME` with a stable `business_code`
  (e.g. `MEMBER_NOT_FOUND`) — never raised as an exception, never confused with a crash.
- **Recoverable — human-in-the-loop** — `recovery="pause"`: creates an intervention, blocks on
  `interventions.wait_for_approval`/`wait_for_resume`, **re-validates the triggering condition
  after resume** before continuing (a real gap that was found and fixed — an earlier version
  trusted the resume blindly).
- **Recoverable — automated retry** — `recovery="retry"`: waits and re-checks the same
  checkpoint up to `max_retries` times before falling through to a hard failure. This was
  missing entirely until a later pass — originally only `pause` was dispatched.
- **Hard failure, with real distinctions between causes** — anything else becomes
  `RunStatus.FAILURE` with a structured `RunError(category, code, step_id, evidence_path)`,
  always with a screenshot. The category is no longer a single generic bucket: a declared
  `ErrorRule` with a non-business category (e.g. `auth`, for a session-expired state) now keeps
  *its own* category instead of collapsing into `checkpoint_failed`; a `LookupError` (locator
  genuinely not found) is `target_not_found`; a driver-level action timeout — translated by
  `PlaywrightSurface` into a domain-level `SurfaceTimeout` rather than leaking a Playwright
  exception into `replay.py` — is `timeout`. This closed a real gap found by grepping
  `replay.py` for every `ErrorCategory.` assignment: `auth`, `target_not_found`, and `timeout`
  were all declared in the schema but never assigned anywhere until this fix.

**Test it:**
```bash
uv run pytest -q -m e2e tests/test_replay_e2e.py                 # business outcome + hard failure
uv run pytest -q -m e2e tests/test_intervention.py                # recoverable: pause/dismiss
uv run pytest -q -m e2e tests/test_replay_recoverable.py          # recoverable: automated retry
uv run pytest -q tests/test_replay_validation.py                  # validation errors, no browser needed
uv run pytest -q tests/test_replay_error_categories.py            # auth (real) + timeout (deterministic fake)
```

**Debug it:** `result.status` and `result.error.category` on any `ExecutionResult` (printed by
the CLI, returned by REST, returned by MCP) tell you immediately which leg of the taxonomy a run
landed in. `result.error.evidence_path` points at a screenshot for anything that failed.

---

## §3.4 — Safety & policy guardrails

> "Enforce an explicit, configurable allowlist... Distinguish safe/reversible from
> risky/irreversible actions, and handle the risky class conservatively (block, require
> confirmation, or flag — your call)... Never persist secrets or raw sensitive data."

**Where:** `src/capability_platform/policy/engine.py` (`PolicyEngine`, `default_policy()`),
`config/policy.json`, `src/capability_platform/agent/discovery.py`
(`ClaudeDiscoveryAgent._classify_risk`), `src/capability_platform/observability/evidence.py`
(`Redactor`).

**How we achieved it:**
- **Allowlist** — `default_policy()` loads real config from `config/policy.json` (not a
  hardcoded duplicate — that was a real gap, fixed): allowed hosts, allowed action types.
  `PolicyEngine.authorize_url`/`.authorize_step` enforce it before every navigation/action.
- **Risk classification, chosen mechanism: require confirmation** — `RiskLevel` is a 4-level
  ordered enum. `ClaudeDiscoveryAgent._classify_risk(action, target)` assigns it **in code,
  deliberately never left to the model to self-report** (a manipulated or mistaken model output
  should not be able to talk its way into a lower risk level for its own step): reads stay
  `read_only`, data entry is `reversible`, a click on a button whose label matches a
  mutating-action keyword (save/submit/update/delete/confirm/pay/transfer/...) is `risky`. This
  was a real gap found late: discovery originally hardcoded every step to `read_only`, so the
  approval gate below could never fire from genuine discovery output.
- **The gate itself** — `PolicyEngine.requires_approval(step)` checks risk against
  `maxRiskWithoutApproval` (config default `reversible`). If exceeded, `ReplayEngine` pauses
  *before* the step runs, creates a same-session intervention, and requires an explicit
  `resume(id, approved=True|False)` — a denial fails with `code="APPROVAL_DENIED"`, never a
  silent pass.
- **Redaction** — `Redactor` regex-scrubs SSN/authorization/api_key/cookie/session_id patterns
  from every structured evidence event before it's written to disk.

**Test it:**
```bash
uv run pytest -q tests/test_models.py::test_policy_blocks_unknown_host
uv run pytest -q tests/test_policy_config.py           # config/policy.json actually drives behavior
uv run pytest -q tests/test_discovery_risk_classification.py   # classifier + full approval chain
uv run pytest -q -m e2e tests/test_approval.py         # approve and deny, both against the real gate
uv run pytest -q tests/test_redaction.py
uv run python scripts/validate_evidence.py             # tree-wide redaction gate over real evidence
```

**Debug it:** to see *why* a step was blocked, check `result.error.category` (`"policy"`) and
`result.error.message` (names the step id and risk level). To see why an intervention was
created for approval, look at `evidence/runs/<run_id>/events.jsonl` for `intervention.created`
— it carries the exact reason string. To check the redaction gate is actually working, look at
`scripts/validate_evidence.py`'s `FORBIDDEN_PATTERNS` list directly.

**Known, disclosed limitation:** the risky-click keyword list is a heuristic, not exhaustive —
an unusually-labeled mutating button (e.g. "Go") could still be missed. Screenshots are never
redacted (only text evidence is) — acceptable here only because the project uses synthetic data.

---

## §3.5 — Evidence / observability

> "A structured log of what the agent did and why, and at least one richer signal on failure
> (screenshot, DOM snapshot, trace, etc.)."

**Where:** `src/capability_platform/observability/evidence.py` — `EvidenceCollector`.

**How we achieved it:** every meaningful moment in discovery and replay calls
`evidence.event(type, **data)`, appended as one redacted JSON line per event to
`evidence/runs/<run_id>/events.jsonl`. Every failure/pause/approval point also calls
`evidence.screenshot(image_bytes, name)` for a full-page PNG. Screenshot capture goes through
`SurfaceAdapter.screenshot()` (see §3.7 below) — `EvidenceCollector` itself takes raw bytes, not
a driver object, so it has no Playwright dependency either.

**Test it:** `uv run pytest -q tests/test_evidence_validation.py` (the redaction gate, run
against the real committed evidence tree). To see a real trace: open any
`evidence/runs/<run_id>/events.jsonl` and read it top to bottom — it's a plain, human-readable
narrative of the run.

**Debug it:** `evidence/INDEX.md` names the exact canonical run for each required scenario
(success, business outcome, hard failure, handoff, etc.) if you want a known-good example to
compare against.

---

## §3.6 — Human-in-the-loop escalation & handoff

> "Identify a stuck/blocked state and raise an intervention request... Let the human operate the
> same live session... then hand control back so the run can resume. automation must be able to
> pause, cede control, and resume on the same session."

**Where:** `src/capability_platform/intervention/manager.py` (`InterventionManager`,
`Intervention`), wired into `computer_use/replay.py`; `src/capability_platform/api/app.py`
(`GET /interventions`, `POST /interventions/{id}/resume`).

**How we achieved it — the same-session part is the whole point, so here's exactly how it's real
and not simulated:** `ReplayEngine` never closes or recreates its `PlaywrightSurface` across a
pause. When a pause-worthy condition is hit, it calls `interventions.create(..., page=surface.page)`
— `InterventionManager` stores that literal, live Playwright `Page` object in an in-process-only
dict (`_pages`, never serialized into the `Intervention` model or any API response).
`interventions.get_page(id)` hands that exact object to whoever is acting as the operator (a
real console, or in our tests, the test itself). They interact with it directly — click a real
button on the real page — then call `resume()`. Replay wakes up on the *same* `Page`, re-observes
it, and — this was a real gap found and fixed — **re-validates** that the condition it paused for
is actually gone before continuing, rather than trusting the resume blindly.

The same mechanism is reused for risky-action approval (§3.4) rather than building a second
escalation path — one real, tested seam instead of two similar-but-different ones.

**Test it:**
```bash
uv run pytest -q -m e2e tests/test_intervention.py   # pause, dismiss on the real page, resume, complete
                                                        # + negative case: resume without dismissing → hard failure
uv run pytest -q -m e2e tests/test_approval.py       # same mechanism, approve/deny a risky step
```
Manually: run with `HEADLESS=false`, trigger a pause, `GET /interventions`, operate the visible
browser by hand, `POST /interventions/<id>/resume`.

**Debug it:** `evidence/runs/<run_id>/events.jsonl` — look for
`intervention.created` → `control.transferred(owner=human)` → `control.transferred
(owner=automation)` → `resume.observed`/`resume.validated`. If a run seems stuck, check
`GET /interventions` to see what's pending and why (`reason` field).

---

## §3.7 — Design for heterogeneity & multi-tenant (design + "don't paint into a corner")

> "How would your artifact schema and replay engine extend to a legacy web app / desktop app...
> How would an artifact be reused across tenants... We don't expect you to implement multi-tenant
> or desktop support. We do expect the core abstractions not to paint you into a corner."

**Where:** `REPORT.md` §4 (the write-up — this is what the PDF actually asks for);
`src/capability_platform/computer_use/surface.py` (`SurfaceAdapter` Protocol,
`PlaywrightSurface`); `models.py` (`ApplicationBinding.tenant_overrides`).

**How we achieved it:** the write-up answers all four sub-questions concretely (per-tenant URL
resolution, a named product/version fingerprint procedure, the override boundary — locator/route
swap only, else a new artifact version — and an explicit statement that authentication is
deliberately *not* designed here). The "don't paint into a corner" half is the one part that's
actually a code check, not a doc check — and it's genuinely true: `ReplayEngine` depends only on
`SurfaceAdapter` (`start`/`close`/`observe`/`navigate`/`wait`/`click`/`type`/`extract`/
`visible`/`value_of`/`current_url`/`screenshot`), injected via a `surface_factory`, never on the
concrete `PlaywrightSurface`. This was a real gap fixed late — `ReplayEngine` used to call raw
Playwright `Page` methods directly for navigate/wait/checkpoints, which would have meant
rewriting the engine to add a desktop adapter.

**Important honesty check:** `tenant_overrides` is a real schema field but **nothing reads it at
runtime** — no code resolves a per-tenant URL or merges an override today. This is intentional
(design-only per the PDF), not an oversight, but don't mistake the field's existence for a
working feature.

**Test it:**
```bash
uv run pytest -q tests/test_surface_adapter.py
```
This is the actual proof: a `FakeSurface` with **zero Playwright import** runs a full capability
through the real `ReplayEngine` — if the abstraction were fake, this test couldn't pass.

**Debug it:** `grep -n "surface\.page" src/capability_platform/computer_use/replay.py` — should
show exactly two lines, both `page=surface.page` inside `interventions.create(...)` calls (the
one deliberate, documented exception — the human-handoff mechanism needs the literal live page).
Anything else there would be a regression of this requirement.

---

## §4 — "The discovery run has to be real" (non-negotiable)

> "At least one genuine LLM-driven run against a live surface, with the evidence in `/evidence/`
> to show it happened. We can't assess a description of it."

**Where:** `evidence/runs/`, `evidence/INDEX.md`.

**How we achieved it:** multiple real discovery runs exist, including two genuine failures
preserved (not hidden) alongside the eventual successes — a schema-ambiguity crash, a
non-generalizing locator, a role/name field-swap the model made on a *different* real run. This
matters: a single cherry-picked success would be weaker evidence than a real run with a real,
diagnosed-and-fixed problem in the trail.

**Test it / see it:** `evidence/INDEX.md` item 1 links the canonical discovery log directly. To
run a fresh one yourself: `uv run capability-platform discover --goal "..."` (needs
`ANTHROPIC_API_KEY`).

**Debug it:** if a discovery run behaves oddly, the full Claude decision at each step
(`discovery.decided` events) shows exactly what it was told and what it chose — this is usually
enough to tell whether it's a prompt/schema clarity issue (fix the prompt) or a genuine app
quirk (fix the demo app or add a fallback rule).

---

## §6 — Deliverables (exact paths the PDF requires)

| Deliverable | Where | Status |
|---|---|---|
| `/README.md` — setup + exact demo commands | `README.md` | Present, kept in sync with the Makefile |
| `/REPORT.md` — exactly 7 headings | `REPORT.md` | Verified verbatim: `grep -n "^## " REPORT.md` |
| `/evidence/` — discovery + replay logs, ideally one error case | `evidence/`, `evidence/INDEX.md` | Present; index names the canonical file for each required scenario |

**Debug it:** `grep -n "^## " REPORT.md` must print exactly: Architecture, Artifact schema,
Determinism & error handling, Heterogeneity & multi-tenant, Escalation & handoff, Safety, Cuts —
in that order, with no extra or missing headings.

---

## §7 — Evaluation anti-goal (not a requirement to satisfy, a risk to manage)

> "We do not reward feature breadth... A small, correct, well-argued system is the goal."

**Where this actually shows up:** REST (`api/app.py`), MCP (`mcp/server.py`),
embeddings/reranking (`capabilities/registry.py`), synthesis (`synthesis/result.py`) all exist,
are real and tested, but are **not required**. `capabilities/registry.py` in particular is fully
unwired — nothing in `discover`/`replay`/REST/MCP ever calls `.search()`; it's a correct,
tested, standalone module, not a half-built live feature. This is intentional and disclosed in
`REPORT.md` §7 ("Cuts") — the recommendation, if you have more time, is to make the load-bearing
pieces above deeper still, not to wire this in without a concrete need.

---

## Stretch / secondary features (not required, built anyway, validated for real)

**REST + MCP** — `src/capability_platform/api/app.py`, `src/capability_platform/mcp/server.py`.
Both are thin adapters over the same `ArtifactStore`/`ReplayEngine` — no duplicate execution
logic, no LLM on either path. Gated by capability `lifecycle`: only `approved`/`active`
capabilities are listed or invocable (`ArtifactStore.list_approved()`,
`AGENT_EXPOSABLE_LIFECYCLES`).

*A real bug lived here for a while*: the `mcp` dependency resolved to a 2.x release that renamed
`FastMCP`→`MCPServer`, so the MCP server couldn't even start until someone actually ran it (not
just read the code) and caught it.

```bash
make platform    # REST on :8000
make mcp          # MCP over stdio
uv run pytest -q -m e2e tests/test_mcp_server.py   # spawns the real server, real client, real call
uv run pytest -q tests/test_capability_gating.py   # proves an unapproved capability is excluded
```

**OpenAI GPT-5 mini discovery fallback** (not a PDF requirement — a stated project direction,
narrowed during review to "fallback only, never a default") —
`src/capability_platform/agent/discovery.py` (`_decide_via_openai`). Claude is always tried
first; only a genuine `anthropic.APIError` (connection/timeout/rate-limit/5xx/auth) triggers a
single-call fallback to GPT-5 mini. Proven with a *real* forced Anthropic failure (an invalid
model name — a real 404, not a mock), which produced a fully correct, generalizable artifact via
GPT-5 mini alone.

```bash
uv run pytest -q tests/test_discovery_fallback.py    # mocked, no real keys needed
# Real proof (needs both keys): force a genuine Anthropic error
CLAUDE_MODEL=claude-invalid-model-xyz uv run capability-platform discover --goal "..."
```

**Debug it:** `evidence.event("discovery.provider_fallback", reason, from_provider,
to_provider)` fires on every fallback — check `events.jsonl` for it. The resulting artifact's
`discovered_by` field accurately records which provider(s) actually made the decisions (a real
bug — it used to always say `anthropic:...` even when OpenAI did the work — was found and fixed
here).

---

## Quick reference — run everything

```bash
# Setup
cp .env.example .env    # ANTHROPIC_API_KEY required; OPENAI_API_KEY optional (fallback only)
make install

# Deterministic-only, no keys, no browser needed for most of it
make test
make lint
uv run python scripts/validate_evidence.py

# Needs the demo app running (make demo, separate terminal)
make test-e2e

# Needs a real ANTHROPIC_API_KEY
make discover
uv run capability-platform approve lookup-member-savings-balance.v1
make replay
```

## Quick reference — where the honest gaps are

- `capabilities/registry.py` (embeddings/reranking) — real, tested, **unwired**.
- `tenant_overrides` — a real schema field, **nothing reads it at runtime**.
- Authentication — **not designed**, disclosed explicitly in `REPORT.md` §4.
- Screenshots — **never redacted** (text evidence is); fine only because all data is synthetic.
- Risky-click classification — a **keyword heuristic**, not exhaustive.
