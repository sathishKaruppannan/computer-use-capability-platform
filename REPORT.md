# Design Report

## 1. Architecture

The system treats computer use as a **capability compiler for applications without APIs**. An
agent goal first searches a normalized registry containing local tools, approved MCP tools,
skills, APIs, and recorded UI capabilities. A lightweight embedding retrieves semantic
candidates; trust, input compatibility, reliability, cost, and risk are the reranking seam. When
no approved deterministic capability fits, Claude enters a bounded observe-decide-act loop over
an accessibility-first Playwright surface. A successful trace is compiled into an artifact,
reviewed, and registered. Subsequent calls go directly to deterministic replay.

The implementation is a modular monolith. That keeps the POC observable and easy to run while
preserving separable boundaries: agent reasoning, capability resolution, policy, surface control,
replay, intervention, evidence, synthesis, and agent-facing transports. The `SurfaceAdapter`
separates semantic actions from Playwright; a desktop accessibility or screenshot-coordinate
adapter can implement the same contract. REST and MCP are adapters over the same application
services, not separate execution paths.

Claude is used only during discovery. Replay has no LLM client, so cost, latency, and behavior are
bounded. A deterministic aggregator owns canonical outputs. The optional synthesizer formats only
those facts and cannot modify them. MCP is both an implemented outbound catalog for learned
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
code, step, expected/observed context, and evidence location. Recoverable conditions can declare a
bounded retry or known recovery; an unknown dialog pauses instead of being dismissed blindly.
Timeout, authentication, target, checkpoint, policy, application, and internal errors are separate
categories. This prioritizes legitimate runtime states over speculative self-healing.

UI drift is handled secondarily through semantic targets, bounded fallbacks, version bindings, and
telemetry on which locator succeeded. Falling below a reliability threshold should move a capability
to `degraded` and prevent unattended execution.

## 4. Heterogeneity & multi-tenant

The artifact describes abstract actions and semantic targets; the surface adapter owns mechanics.
Web uses Playwright accessibility/DOM data. Legacy frames can add frame paths and table-relative
XPath. Desktop can map role/name/value to UI Automation or AX APIs, with screenshot coordinates as
the last fallback. The replay engine and error contract do not change.

Artifacts bind to vendor/product and supported application versions, not directly to one tenant.
Tenants inherit a vendor-base artifact and may supply narrow locator/route overrides. On startup or
deployment, a fingerprint (title, landmarks, version text, and selected structural hashes) selects
the compatible variant. Canary replay and locator telemetry detect drift. Overrides that diverge
substantially become a new version rather than accumulating unsafe conditional logic. This supports
reuse across institutions while failing closed when compatibility is uncertain.

## 5. Escalation & handoff

Discovery escalates on a dead end, step limit, or unsafe request. Replay escalates for a declared
pause condition, an unknown obstructing state, or risk requiring approval. The intervention contains
the run/capability, current step, reason, accessibility state, and screenshot.

Control ownership is explicit: `automation` or `human`. The automation pauses before ownership
transfers. The browser remains the same live object/session; a human operates that session and sends
a resume signal. The POC re-observes that same session before continuing; a capability-specific
resume checkpoint is the next hardening step. Every transfer and operator action is part of the
same trace. The POC implements ownership and resume signaling in process and uses a visible
browser as the minimal operator surface; remote streaming and identity integration are clean next
layers.

## 6. Safety

Policy is code/config outside the model. It allowlists hosts and action types, classifies each step as
read-only, reversible, risky, or irreversible, and requires approval above a configured threshold.
The planner cannot expand permission. Browser/tool/MCP output is untrusted data and is not inserted as
system instruction. External MCP capabilities must be normalized, publisher-verified, allowlisted,
scope-reviewed, and data-classification compatible before becoming selectable.

Evidence is structured and redacted before disk writes. Credentials, tokens, cookies, full SSNs, and
raw sensitive inputs are not permitted in artifacts. A real deployment also needs isolated workers,
an enterprise secrets manager, encrypted short-lived session state, tenant-scoped RBAC, append-only
audit storage, egress controls, and DLP. This POC is not appropriate for real banking data.

## 7. Cuts

Implemented deeply enough to demonstrate the vertical slice: real Claude discovery, a typed artifact,
deterministic replay, explicit business outcomes, independent policy, evidence/screenshots, same-session
handoff primitives, semantic capability retrieval, REST, MCP exposure, one composable skill, and grounded
synthesis.

Deliberately cut: internet-wide MCP discovery/installation, multiple authentication modes, distributed
queues, production operator streaming, enterprise secrets/RBAC, persistent intervention storage, desktop
automation, and real multi-tenancy. They add operational breadth but do not improve the load-bearing
assignment decisions. Next I would add resume-state verification, schema-generated input validation,
bounded retry policies, artifact signing and approval, an accessibility-based desktop adapter, and a
multi-run evaluation harness that reports primary/fallback locator rates and stability.
