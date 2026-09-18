# Design Report

## 1. Architecture

The system treats computer use as a **capability compiler for applications without APIs**. A
free-text agent goal is never sent straight to computer-use discovery: it first passes through an
Intent Analyzer (LLM call, structured `TaskIntent` out), a deterministic Planner (no LLM,
`TaskIntent` → one or more typed `PlanStep`s), and a Capability Resolver that searches a
normalized registry containing local tools, approved MCP tools, skills, APIs, and recorded UI
capabilities — a lightweight embedding retrieves semantic candidates, and exact input/output
compatibility, trust, policy, tenant, and source-priority reranking decide what's actually
selectable. When no approved deterministic capability fits, Claude enters a bounded
observe-decide-act loop over an accessibility-first Playwright surface. A successful trace is
compiled into an artifact, reviewed, and registered. Subsequent calls go directly to deterministic
replay.

**What's actually wired up today:** the semantic embedding/reranking registry
(`capabilities/registry.py`) is connected to the real runtime via `build_registry()` and queried
by `capabilities/resolver.py` on every `capability-platform plan`/`run` call and every
`POST /agent/plan`/`/agent/execute` request — not just exercised by its own unit test anymore.
A second, independent, older resolution path still exists and is unchanged: the authenticated
REST surface's `POST /v1/discover` takes `(service_type, system_identifier)` and checks
`ArtifactStore.find_approved_by_service_and_system` first — a hit reuses the existing capability
with zero LLM calls, cross-client, before ever falling back to Claude discovery on a miss. That's
exact-key reuse, not semantic retrieval, and it predates the general resolver above; unifying the
two (or deprecating the exact-key path in favor of the semantic one) is a natural next step, not
yet done.

The implementation is a modular monolith. That keeps the POC observable and easy to run while
preserving separable boundaries: agent reasoning, capability resolution, policy, surface control,
replay, intervention, evidence, synthesis, and agent-facing transports. The `SurfaceAdapter`
separates semantic actions from Playwright; a desktop accessibility or screenshot-coordinate
adapter can implement the same contract. REST and MCP are adapters over the same application
services, not separate execution paths.

Claude is used in exactly two places, both behind a provider-independent seam
(`llm/provider.py`, with Anthropic/OpenAI/mock implementations): computer-use discovery
(`agent/discovery.py`) and intent analysis (`agent/intent_analyzer.py`). Neither the Planner nor
the deterministic replay path ever instantiates an LLM client — replay has no LLM client at all,
so cost, latency, and behavior stay bounded on the production execution path. OpenAI's GPT-5 mini
is available as a per-call fallback if a single Anthropic call errors mid-run (never a default,
never used while Anthropic is healthy) — a project direction independent of the assignment
itself, since LLM choice is explicitly left to the candidate. A deterministic aggregator owns
canonical outputs (exact-key dict copy from each step's typed result, no LLM, no derivation). The
optional synthesizer formats only those facts and cannot modify them — it takes no LLM provider
as input at all, so there is no code path for a model's raw output to reach a numeric or entity
value in the synthesized text. MCP is both an implemented outbound catalog for learned
capabilities and a future normalized input source; dynamic installation of arbitrary servers is
deliberately excluded because discovery is not trust.

## 2. Artifact schema

`CapabilityArtifact` is the central contract. It includes a stable ID and version; human-readable
name and purpose; lifecycle/approval state; vendor, product, supported version, base route, and
tenant overrides; typed inputs and outputs; ordered steps; locator sets with rationale; risk per
step; explicit error rules; and a final success checkpoint.

Targets use one primary locator plus ordered fallbacks. Semantic role/name or label locators are
preferred because they survive markup changes and map conceptually to desktop accessibility.
CSS/XPath and coordinates are lower-quality fallbacks. Recording rationale makes fragility visible
during review. Runtime values use named templates such as `{{memberId}}`; raw discovery values and
credentials never belong in the artifact.

The schema does not serialize a raw model transcript. It captures executable intent and contracts,
keeping the artifact reviewable by both people and calling agents. JSON was selected for portability
and MCP/REST schema compatibility. A production store would add immutable hashes, signatures,
schema migration, and optimistic versioning.

## 3. Determinism & error handling

Replay validates arguments, independently authorizes the app URL and every action, resolves each
target through an ordered locator strategy, executes exactly one declared operation, evaluates
known error rules, and verifies checkpoints. It never asks a model what to do next. Extraction is
mapped to declared output names and the final success condition must pass before returning success.

The result contract distinguishes: `success` with typed outputs; `business_outcome` with a stable
domain code such as `MEMBER_NOT_FOUND`; `paused` with an intervention ID; and `failure` with category,
code, step, expected/observed context, and evidence location. Recoverable conditions declare a
known recovery: `pause` (human dismissal, exercised end-to-end), a bounded `retry` (waits and
re-checks the same checkpoint up to `max_retries` times before falling through to a hard
failure), or `return`/`fail`.
An unknown dialog pauses instead of being dismissed blindly.
Timeout, authentication, target, checkpoint, policy, application, and internal errors are separate
categories. This prioritizes legitimate runtime states over speculative self-healing.

UI drift is handled secondarily through semantic targets, bounded fallbacks, version bindings, and
telemetry on which locator succeeded. Falling below a reliability threshold should move a capability
to `degraded` and prevent unattended execution.

## 4. Heterogeneity & multi-tenant

The artifact describes abstract actions and semantic targets; the surface adapter owns mechanics,
and `ReplayEngine` depends only on the `SurfaceAdapter` Protocol (`start`/`close`/`observe`/
`navigate`/`wait`/`click`/`type`/`extract`/`visible`/`value_of`/`current_url`/`screenshot`) —
never on `PlaywrightSurface` directly, injected via a `surface_factory`. Proven, not just
declared: `tests/test_surface_adapter.py` runs a full capability through `ReplayEngine` against
a fake adapter with zero Playwright import. The one deliberate exception is the same-session
human-handoff mechanism, which hands a human/operator the literal live Playwright `Page` — that's
inherent to what "same session" means for a browser surface, not a determinism-path leak. Web
uses Playwright accessibility/DOM data; legacy frames can add frame paths and table-relative
XPath through the same `Locator` model.

**Desktop `SurfaceAdapter` — design (PDF §3.7: "design, not necessarily build").** A
`DesktopSurface` implementing the same Protocol needs no change to `ReplayEngine`, `Step`,
`Locator`, or the error contract — only a new mapping from `Locator.strategy`/`value`/`name` to a
platform accessibility API, exactly as `PlaywrightSurface` maps them to Playwright's own
role/label/text/css/xpath selectors today:

| `Locator.strategy` | Web (`PlaywrightSurface`, today) | Desktop (design) |
|---|---|---|
| `role` | ARIA role + accessible name | Windows UI Automation `ControlType` + `Name`, or macOS `AXRole`/`AXTitle` |
| `label` | associated `<label>` text | UIA `LabeledBy` / AX `AXDescription` |
| `text` | visible text content | UIA `Name`/`ValuePattern`, AX `AXValue` |
| `css` / `xpath` | DOM query | not meaningful on desktop — a `DesktopSurface` would reject these strategies at discovery/replay time rather than silently degrading, so a desktop artifact never depends on a locator kind it can't actually resolve |
| coordinates (fallback) | pixel click via Playwright | pixel click via OS-level input injection (already the documented last resort for both surfaces) |

`observe()` returns the same shape `_decide()` already consumes (a serialized accessibility
tree), built from `UIAutomation`/`pywinauto` on Windows or the `AXUIElement` tree via `pyobjc` on
macOS instead of Playwright's accessibility snapshot — the discovery loop and its prompt don't
change, since they already reason over "the current accessible-tree observation," not "the
current DOM." `click`/`type`/`extract`/`visible`/`current_url` (desktop: current window title,
the closest analog) map onto the equivalent platform calls. The `screenshot()` method and
coordinate-fallback locator already exist for exactly this "no other reliable signal" case. What
stays a real cut: an actual `DesktopSurface` implementation and a second target application to
prove it against — this project implements against one concrete (web) surface per the PDF's own
brief, and building desktop automation purely to exercise this design would be the kind of
breadth the PDF explicitly doesn't reward.

Artifacts bind to vendor/product and supported application versions, not directly to one tenant,
so the same recorded flow is reused across every institution running that product rather than
re-recorded per tenant. Four concrete questions this needs to answer, and how:

**Per-tenant URL.** `ApplicationBinding.base_url` is the vendor-reference URL used during
discovery. Each tenant is registered once with a `tenant_id` and its real hostname, stored in
`tenant_overrides[tenant_id].base_url`. A replay invocation always carries an explicit
`tenant_id` (threaded through the REST/MCP/CLI call, not inferred); the effective URL is
`tenant_overrides.get(tenant_id, {}).get("base_url", application.base_url)`, resolved once at
the top of the run before `PolicyEngine.authorize_url` runs. The allowlist is tenant-aware too —
each tenant's real hostname must be explicitly present in policy config; there is no wildcard
"any tenant subdomain" rule, so onboarding a tenant is an explicit, reviewable policy change,
not an implicit one.

**Product/version validation (the fingerprint).** Before trusting a tenant's binding, compare a
small fingerprint of its live entry screen against the fingerprint recorded for each
`supported_versions` variant: page `<title>`, top-level navigation landmarks and their labels, a
version string if the app exposes one (footer/about page/meta tag), and a structural hash of the
entry screen's accessibility-tree role/label skeleton (roles and labels, not their text values,
so it's stable across tenants' branding/data). If the live fingerprint matches a known variant
within a similarity threshold, replay proceeds against that variant's overrides. If it matches
none, replay refuses to run unattended — it fails closed and raises the same escalation path as
an unresolved recoverable condition, flagging the tenant for a fresh discovery/review pass rather
than silently guessing.

**Per-tenant screen navigation.** Steps keep a stable `id`. A tenant override is a small, additive
patch keyed by that id — e.g. `tenant_overrides[tenant_id].steps["search"].target` supplies an
alternate locator when a tenant's build uses a different label for an otherwise-identical
button. Action type, order, and count stay fixed; overrides may only swap a `Target` or a route
fragment, never insert, remove, or reorder steps. That's the deliberate boundary: a locator/route
swap is a safe, reviewable override; anything larger (a genuinely different flow) means the
tenant isn't running a compatible variant, and the right move is a new artifact version, not
conditional branching accumulating inside one artifact. Canary replay and per-locator success
telemetry catch drift between recordings, well before it would cause a silent wrong answer in
production.

**Multi-tenant authentication — design (Phase 11; per the PDF's own §3.7 scope, "design, not
necessarily build").** `ErrorCategory.AUTH` already exists so replay can *classify* an auth
failure distinctly from other hard failures. The design that closes this gap without inventing a
second artifact model:

- **A login capability is its own versioned `CapabilityArtifact`, not a step embedded in every
  other artifact.** Same schema as any other capability — `inputs` declares the credential
  fields it needs (`username`/`password`, or `apiKey`, exactly the `ParameterSpec(sensitive=True)`
  shape `_credential_input_specs` already builds for the demo's `/secure/*` flow), `outputs`
  declares what it produces (a session token/cookie identifier), and its `steps` are ordinary
  navigate/type/click/checkpoint steps like any other artifact — the login form *is* just another
  UI flow to discover once and replay deterministically, no new mechanism needed.
- **`ApplicationBinding` gains an `auth_mode: Literal["none", "credentials", "session_cookie",
  "api_key", "sso"] | None` field and, when not `"none"`, a `login_capability_id` reference.**
  `tenant_overrides[tenant_id]` can override both, so two tenants on the same vendor product can
  run different auth modes (one SSO, one basic) against the same base recorded flow. SSO
  (SAML/OIDC redirect) is the one mode that can't be driven by typed username/password fields the
  same way — its login capability's `inputs` would instead reference a pre-established session
  artifact (see below) rather than raw credentials, since a redirect-based flow isn't meaningfully
  parameterizable the way a form post is.
- **Session lifecycle, not per-call credentials.** `ExecuteV1Request.inputs` carrying raw
  credentials on every single call would be exactly the kind of credential handling CLAUDE.md
  rule 3 exists to prevent. Instead: `ReplayEngine`, before running an artifact whose binding
  declares `auth_mode != "none"`, checks a per-`(tenant_id, application)` session cache (cookie
  jar / bearer token, keyed and TTL'd, held in the same trust boundary as `access/credentials.py`
  today — never written into an artifact or an evidence log). A cache miss or an `AUTH`-category
  checkpoint failure mid-run (the demo already has a real analog: member `10005` simulates an
  expired session) triggers the login capability once via the existing `ReplayEngine`/
  `CapabilityExecutor` machinery, caches the resulting session, then retries the original step —
  the same bounded-retry shape `ErrorRule.recovery="retry"` already implements, just retrying
  after a re-auth instead of a wait.
- **Credentials themselves live in a secrets store keyed by `tenant_id`**, resolved at the moment
  the login capability runs — never passed through `context`/request bodies from a calling agent,
  never logged. `access/credentials.py`'s existing PBKDF2-hashed-at-rest pattern is the right
  shape for *client* credentials; tenant-application credentials would need their own store with
  the same trust properties (hashed/encrypted at rest, never round-tripped in a response body),
  which is real infrastructure this project doesn't build — the design boundary is exactly the
  `access/` package seam already established.

What stays a real cut, honestly: an actual secrets-vault implementation, and a second working
example of a non-credentials `auth_mode` (only the demo's basic-auth `/secure/*` flow is real and
evidenced) — building either would be exactly the "scaling infrastructure" the PDF says isn't
rewarded for a project scoped to one concrete surface.

## 5. Escalation & handoff

Discovery escalates on a dead end, step limit, or unsafe request. Replay escalates for a declared
pause condition, an unknown obstructing state, or risk requiring approval. The intervention contains
the run/capability, current step, reason, accessibility state, and screenshot.

Control ownership is explicit: `automation` or `human`. The automation pauses before ownership
transfers. The browser remains the same live object/session; a human operates that session and sends
a resume signal. The POC re-observes that same session and re-evaluates the triggering error
rule's own checkpoint before continuing — if the condition is still present, the run fails hard
with a clear message rather than silently proceeding as if a human had fixed it. Every transfer
and operator action is part of the same trace. The POC implements ownership and resume signaling
in process and uses a visible browser as the minimal operator surface; remote streaming and
identity integration are clean next layers.

## 6. Safety

Policy is code/config outside the model, loaded from `config/policy.json` (not duplicated
in Python). It allowlists hosts and action types, classifies each step as read-only, reversible,
risky, or irreversible, and requires approval above a configured threshold. Approval reuses the
same same-session intervention mechanism as an unexpected-condition handoff, rather than a
second escalation path: before a risky/irreversible step runs, replay pauses and creates an
intervention; a human approves or denies via `resume(approved=True|False)`; a denial fails the
run with a structured `APPROVAL_DENIED` error instead of proceeding. The planner cannot expand
permission — nothing about the model's own output can set `approved=True`. Browser/tool/MCP
output is untrusted data and is not inserted as system instruction. External MCP capabilities
must be normalized, publisher-verified, allowlisted, scope-reviewed, and data-classification
compatible before becoming selectable.

Evidence is structured and redacted before disk writes. Credentials, tokens, cookies, full SSNs, and
raw sensitive inputs are not permitted in artifacts. A real deployment also needs isolated workers,
an enterprise secrets manager, encrypted short-lived session state, tenant-scoped RBAC, append-only
audit storage, egress controls, and DLP. This POC is not appropriate for real banking data.

## 7. Cuts

Implemented deeply enough to demonstrate the vertical slice: a real Claude discovery run against
the live demo app (two genuine defects were found and fixed along the way — a tool-schema
ambiguity that crashed on `extract`, and a locator that captured one input's value instead of a
stable reference), a typed and lifecycle-gated artifact, deterministic replay with input-contract
validation and structured error/business-outcome handling, independent policy, evidence with an
automated redaction-validation gate, a fully exercised same-session handoff (pause, human
dismissal on the live page, resume, checkpoint re-validation, completion — including the negative
case where an unresolved condition correctly fails hard), semantic capability retrieval, REST, MCP
exposure (validated end-to-end with a real client against a real spawned server), one composable
skill, and grounded synthesis.

Deliberately cut: internet-wide MCP discovery/installation, multiple authentication modes, distributed
queues, production operator streaming, enterprise secrets/RBAC, persistent intervention storage, desktop
automation, and real multi-tenancy. They add operational breadth but do not improve the load-bearing
assignment decisions. Resume-state checkpoint verification, schema-driven input validation, the bounded `retry`
recovery dispatch, and a wired approval gate for risky/irreversible steps (pause, explicit
`resume(approved=True|False)`, a denial failing hard with `APPROVAL_DENIED` rather than
proceeding) — all listed here in earlier drafts as future work — are now implemented (see
Determinism & error handling, Escalation & handoff, and Safety). What's still genuinely
outstanding: artifact signing, an accessibility-based desktop adapter, and a multi-run evaluation
harness that reports primary/fallback locator rates and stability.

**Update (Phase 10) — the gap above is closed.** The Planner and `ClaudeDiscoveryAgent` are no
longer scenario-scoped. `ClaudeDiscoveryAgent.discover()` now requires the model to declare and
have re-verified its own completion checkpoint (`strategy`/`value`/`name`, the same vocabulary
already used for click/extract) instead of checking a fixed "Savings Account" text oracle, and
accepts optional `capability_hint`/`name_hint`/`description_hint`/`output_*_hint` params —
supplied by the orchestrator from the resolved `TaskIntent` — that steer the compiled artifact's
id/name/description/output instead of always producing the one hardcoded savings-balance
identity. `TaskIntent` gained an optional `sub_goals` field, populated by the same intent-analysis
LLM call (not a second one), that the Planner turns directly into sequential `PlanStep`s for a
compound goal — no template-key guessing required.

Both were proven with genuine, live Claude calls, not just deterministic tests: a goal shaped
nothing like the original scenario ("confirm member 10001's account status is active") produced a
real artifact `retrieve-member-account-status.v1` with checkpoint `"Status: Active"` and output
`accountStatus` — none of it hardcoded; and the exact compound goal that previously fell back to
one generic step ("find member 10001, retrieve the savings balance, and create a servicing note")
now genuinely decomposes into 3 steps that resolve to 3 different outcomes for real: step-1
(lookup) → `COMPUTER_USE_DISCOVERY`, step-2 (balance) → `COMPUTER_USE_CAPABILITY` selecting the
real `lookup-member-savings-balance.v1`, step-3 (note) → `COMPUTER_USE_DISCOVERY`. See TASKS.md
Phase 10 for the full evidence trail and run ids. A related real bug was found and fixed in the
same phase: an unsatisfiable plan (a required input the goal never supplied, e.g. the note's
content) previously crashed the CLI/REST layer with a raw traceback instead of a clean 400/error
— `PlanValidator`'s rejection was correct, but nothing caught it at the boundary. Fixed.

What's still out of scope, honestly: `demo_app` itself only has the one member-lookup/accounts
surface, so a goal needing a genuinely different *page* (not just a different checkpoint on the
existing pages) — e.g. an actual "account preferences" screen, or a real note-creation form —
still can't complete, because the UI to complete it against doesn't exist. That's an app-surface
gap, not a discovery-agent hardcoding gap, and building new demo-app pages purely to close it
would be exactly the kind of feature breadth the assignment says isn't rewarded.
