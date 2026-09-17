# Design Report

## 1. Architecture

The system treats computer use as a **capability compiler for applications without APIs**. The
intended design: an agent goal first searches a normalized registry containing local tools,
approved MCP tools, skills, APIs, and recorded UI capabilities; a lightweight embedding retrieves
semantic candidates; trust, input compatibility, reliability, cost, and risk are the reranking
seam. When no approved deterministic capability fits, Claude enters a bounded observe-decide-act
loop over an accessibility-first Playwright surface. A successful trace is compiled into an
artifact, reviewed, and registered. Subsequent calls go directly to deterministic replay.

**What's actually wired up today:** the semantic embedding/reranking registry piece
(`capabilities/registry.py`) is implemented and unit-tested in isolation, but nothing calls it
yet. A simpler, key-based resolver is wired, though: the authenticated REST surface's
`POST /v1/discover` takes `(service_type, system_identifier)` and checks
`ArtifactStore.find_approved_by_service_and_system` first — a hit reuses the existing capability
with zero LLM calls, cross-client, before ever falling back to Claude discovery on a miss. That's
exact-key reuse, not semantic retrieval; wiring the embedding registry in front of it for
fuzzier goal matching is the natural next step, not yet done.

The implementation is a modular monolith. That keeps the POC observable and easy to run while
preserving separable boundaries: agent reasoning, capability resolution, policy, surface control,
replay, intervention, evidence, synthesis, and agent-facing transports. The `SurfaceAdapter`
separates semantic actions from Playwright; a desktop accessibility or screenshot-coordinate
adapter can implement the same contract. REST and MCP are adapters over the same application
services, not separate execution paths.

Claude is the only LLM used during discovery, and only during discovery; replay has no LLM
client, so cost, latency, and behavior are bounded. OpenAI's GPT-5 mini is available as a
per-call fallback if a single Anthropic call errors mid-run (never a default, never used while
Anthropic is healthy) — a project direction independent of the assignment itself, since LLM
choice is explicitly left to the candidate. A deterministic aggregator owns canonical outputs.
The optional synthesizer formats only those facts and cannot modify them. MCP is both an
implemented outbound catalog for learned capabilities and a future normalized input source;
dynamic installation of arbitrary servers is deliberately excluded because discovery is not
trust.

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
XPath through the same `Locator` model; desktop can map role/name/value to UI Automation or AX
APIs behind a new `SurfaceAdapter` implementation, with screenshot coordinates as the last
fallback — no change to `ReplayEngine` or the error contract required.

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

**Authentication is the one piece deliberately left open, not designed here** (see Cuts) —
`ErrorCategory.AUTH` exists so replay can *classify* an auth failure distinctly from other hard
failures, but there's no login-flow design, credential strategy, or per-tenant auth-mode
selection (SSO/basic/session-cookie/API key) in this artifact model. A real version would need a
separate, versioned "login capability" per auth mode that a tenant's binding references as a
precondition, with its own stricter redaction rules — credentials must never enter an artifact
or an evidence log — but that's a distinct piece of design this project doesn't attempt.

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
