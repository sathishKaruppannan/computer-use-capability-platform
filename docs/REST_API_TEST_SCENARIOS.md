# REST API test scenarios

A copy-paste curl script for demoing and exercising every branch of the REST surface: valid vs.
invalid credentials, authorized vs. unauthorized clients, an existing capability invoked by id,
and a brand-new capability discovered from a goal. Every response below (except where marked
"illustrative") is **real output**, captured from a live local run against this repo's actual
demo app and platform API — not hand-written.

**Scope note:** this document covers the REST surface only (legacy + authenticated `/v1`). It
does not compare REST against the CLI or MCP entry points, or explain when a client call is
genuine Claude discovery vs. a reuse or a plain execute — see
[`ARCHITECTURE_WALKTHROUGH.md`](ARCHITECTURE_WALKTHROUGH.md)'s "Client flow options" section for
that cross-surface comparison (Flow A/B/C).

## 0. Prerequisites

```bash
make demo       # terminal 1 — demo app on :8001
make platform   # terminal 2 — platform API on :8000
```

Credentials used below (all registered via `capability-platform register-client`, stored under
`data/credentials/`, never committed):

| client_id | password | admin | authorized `service_type`s |
|---|---|---|---|
| `demo-client` | `secret123` | yes | `member_savings_balance_lookup` |
| `viewer-client` | `viewer123` | no | `member_savings_balance_lookup` |
| `no-access-client` | `noaccess123` | no | *(none)* |

```bash
uv run capability-platform register-client --client-id demo-client --password secret123 \
  --service-type member_savings_balance_lookup --admin
uv run capability-platform register-client --client-id viewer-client --password viewer123 \
  --service-type member_savings_balance_lookup
```

`no-access-client` (zero authorized service types) can't be created through the CLI — it requires
at least one `--service-type` — so it's registered directly:

```bash
uv run python -c "
from capability_platform.access.credentials import hash_password
from capability_platform.access.models import ClientCredential
from capability_platform.runtime import credential_store

pw_hash, pw_salt = hash_password('noaccess123')
credential_store().save(ClientCredential(
    client_id='no-access-client', password_hash=pw_hash, password_salt=pw_salt,
    authorized_service_types=[], is_admin=False,
))
"
```

---

## 1. Legacy unauthenticated REST (`/capabilities`, `/capabilities/{id}/execute`)

No credentials at all — kept for local/demo convenience, documented in the main
[README](../README.md#rest).

### 1.1 List approved capabilities

```bash
curl -s -w '\nHTTP %{http_code}\n' http://127.0.0.1:8000/capabilities
```

```json
[
  {
    "id": "lookup-member-savings-balance.v1",
    "name": "Lookup member savings balance",
    "inputs": [
      { "name": "memberId", "type": "string", "description": "Demo member identifier", "required": true, "sensitive": false, "pattern": "^\\d{5}$" }
    ],
    "outputs": [
      { "name": "savingsBalance", "type": "number", "description": "Current savings balance", "sensitive": false }
    ]
  }
]
HTTP 200
```

### 1.2 Execute an existing capability by id — success

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST \
  http://127.0.0.1:8000/capabilities/lookup-member-savings-balance.v1/execute \
  -H 'content-type: application/json' -d '{"inputs":{"memberId":"10002"}}'
```

```json
{
  "run_id": "5aa25f1d-c514-4a24-bc51-68a23f3b0b77",
  "status": "success",
  "capability_id": "lookup-member-savings-balance.v1",
  "outputs": { "savingsBalance": 1220.0 },
  "business_code": null,
  "error": null,
  "intervention_id": null,
  "started_at": "2026-09-15T22:34:28.390324Z",
  "completed_at": "2026-09-15T22:34:30.100693Z"
}
HTTP 200
```

### 1.3 Execute an existing capability by id — recoverable business outcome

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST \
  http://127.0.0.1:8000/capabilities/lookup-member-savings-balance.v1/execute \
  -H 'content-type: application/json' -d '{"inputs":{"memberId":"99999"}}'
```

```json
{
  "run_id": "615a6f2e-7add-43a7-a1b7-43959fa78146",
  "status": "business_outcome",
  "capability_id": "lookup-member-savings-balance.v1",
  "outputs": {},
  "business_code": "MEMBER_NOT_FOUND",
  "error": null,
  "intervention_id": null,
  "started_at": "2026-09-15T22:34:30.189003Z",
  "completed_at": "2026-09-15T22:34:30.996209Z"
}
HTTP 200
```

`status` distinguishes this from a hard failure — see [Architecture rules #6](../CLAUDE.md).
`memberId` must match `^\d{5}$` (the artifact's own input pattern); `10001`–`10003` and `99999`
are the demo app's seeded ids (`demo_app/app.py`).

### 1.4 Execute an unknown capability id — 404

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST \
  http://127.0.0.1:8000/capabilities/does-not-exist.v1/execute \
  -H 'content-type: application/json' -d '{"inputs":{"memberId":"10002"}}'
```

```json
{ "detail": "Capability not found" }
HTTP 404
```

---

## 2. Authenticated `/v1` surface — negative auth/authz cases

Every `/v1` route requires HTTP Basic auth. These all fail **before any replay or Claude call
runs** (`src/capability_platform/api/auth.py`).

### 2.1 No credentials — 401

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:8000/v1/discover \
  -H 'content-type: application/json' \
  -d '{"service_type":"member_savings_balance_lookup","system_identifier":"legacy-member-servicing-demo","client_inquiry_id":"x","goal":"g"}'
```

```json
{ "detail": "Not authenticated" }
HTTP 401
```

### 2.2 Wrong password for a real client — 401

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:8000/v1/discover \
  -u demo-client:wrong-password -H 'content-type: application/json' \
  -d '{"service_type":"member_savings_balance_lookup","system_identifier":"legacy-member-servicing-demo","client_inquiry_id":"x","goal":"g"}'
```

```json
{ "detail": "Invalid client credentials" }
HTTP 401
```

### 2.3 Unregistered client — 401

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:8000/v1/discover \
  -u ghost-client:whatever -H 'content-type: application/json' \
  -d '{"service_type":"member_savings_balance_lookup","system_identifier":"legacy-member-servicing-demo","client_inquiry_id":"x","goal":"g"}'
```

```json
{ "detail": "Invalid client credentials" }
HTTP 401
```

(Same message as 2.2 — an unregistered `client_id` and a wrong password are indistinguishable to
the caller by design, so credential guessing can't be used to enumerate valid client ids.)

### 2.4 Valid credentials, not authorized for the requested `service_type` — 403

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:8000/v1/discover \
  -u no-access-client:noaccess123 -H 'content-type: application/json' \
  -d '{"service_type":"member_savings_balance_lookup","system_identifier":"legacy-member-servicing-demo","client_inquiry_id":"x","goal":"g"}'
```

```json
{ "detail": "Client 'no-access-client' is not authorized for service_type=member_savings_balance_lookup" }
HTTP 403
```

### 2.5 Unknown `system_identifier` — 400

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:8000/v1/discover \
  -u demo-client:secret123 -H 'content-type: application/json' \
  -d '{"service_type":"member_savings_balance_lookup","system_identifier":"totally-unregistered-system","client_inquiry_id":"x","goal":"g"}'
```

```json
{ "detail": "Unknown system_identifier: totally-unregistered-system" }
HTTP 400
```

`system_identifier` must be pre-registered in `config/system_registry.json` — clients can't point
discovery at an arbitrary URL.

### 2.6 Non-admin credential calling `/approve` — 403

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST \
  http://127.0.0.1:8000/v1/capabilities/lookup-member-savings-balance.v1/approve \
  -u viewer-client:viewer123
```

```json
{ "detail": "Client is not authorized to approve capabilities" }
HTTP 403
```

### 2.7 Unknown capability id on `/v1` execute — 404

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST \
  http://127.0.0.1:8000/v1/capabilities/does-not-exist.v1/execute \
  -u demo-client:secret123 -H 'content-type: application/json' \
  -d '{"client_inquiry_id":"scenario-012","inputs":{"memberId":"10002"}}'
```

```json
{ "detail": "Capability not found" }
HTTP 404
```

### 2.8 Non-admin credential calling `/capabilities/pending` — 403

```bash
curl -s -w '\nHTTP %{http_code}\n' http://127.0.0.1:8000/v1/capabilities/pending \
  -u viewer-client:viewer123
```

```json
{ "detail": "Client is not authorized to view the approval queue" }
HTTP 403
```

### 2.9 Non-admin credential calling `/{id}/review` — 403

```bash
curl -s -w '\nHTTP %{http_code}\n' \
  http://127.0.0.1:8000/v1/capabilities/lookup-member-savings-balance.v1/review \
  -u viewer-client:viewer123
```

```json
{ "detail": "Client is not authorized to review capabilities" }
HTTP 403
```

---

## 3. "Existing capability, by id" — a client that already knows `capability_id`

This is the fast path: a repeat caller who cached `capability_id` from an earlier `/v1/discover`
response skips discovery entirely and calls execute directly. No Claude call, no resolver lookup.

### 3.1 Valid, authorized client — success

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST \
  http://127.0.0.1:8000/v1/capabilities/lookup-member-savings-balance.v1/execute \
  -u demo-client:secret123 -H 'content-type: application/json' \
  -d '{"client_inquiry_id":"scenario-010","inputs":{"memberId":"10002"}}'
```

```json
{
  "run_id": "b2f74799-5dba-47c8-9630-6ce44757e676",
  "status": "success",
  "capability_id": "lookup-member-savings-balance.v1",
  "outputs": { "savingsBalance": 1220.0 },
  "business_code": null,
  "error": null,
  "intervention_id": null,
  "started_at": "2026-09-15T22:34:46.454378Z",
  "completed_at": "2026-09-15T22:34:47.280232Z"
}
HTTP 200
```

### 3.2 Same client, member that doesn't exist — business outcome

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST \
  http://127.0.0.1:8000/v1/capabilities/lookup-member-savings-balance.v1/execute \
  -u demo-client:secret123 -H 'content-type: application/json' \
  -d '{"client_inquiry_id":"scenario-011","inputs":{"memberId":"99999"}}'
```

```json
{
  "run_id": "d8b09cfd-0428-4187-8263-9f7712ccdfea",
  "status": "business_outcome",
  "capability_id": "lookup-member-savings-balance.v1",
  "outputs": {},
  "business_code": "MEMBER_NOT_FOUND",
  "error": null,
  "intervention_id": null,
  "started_at": "2026-09-15T22:34:47.403689Z",
  "completed_at": "2026-09-15T22:34:48.114709Z"
}
HTTP 200
```

### 3.3 A gotcha worth knowing: `service_type` gating only applies to artifacts that carry one

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST \
  http://127.0.0.1:8000/v1/capabilities/lookup-member-savings-balance.v1/execute \
  -u no-access-client:noaccess123 -H 'content-type: application/json' \
  -d '{"client_inquiry_id":"scenario-015","inputs":{"memberId":"10002"}}'
```

```json
{
  "run_id": "56c2373b-3666-42dd-9e7d-0427373b08dd",
  "status": "success",
  "capability_id": "lookup-member-savings-balance.v1",
  "outputs": { "savingsBalance": 1220.0 },
  "business_code": null,
  "error": null,
  "intervention_id": null,
  "started_at": "2026-09-15T22:34:52.839800Z",
  "completed_at": "2026-09-15T22:34:53.676163Z"
}
HTTP 200
```

`no-access-client` is authorized for **nothing** and this still succeeds — because at the time
this scenario was captured, `artifacts/lookup-member-savings-balance.v1.json` predated the
`service_type` field and had it set to `null`. `execute_v1` only calls `require_service_type`
when `artifact.service_type is not None` (`v1_routes.py:131-132`), a deliberate compatibility
rule for legacy artifacts, called out in code as a known gap: *"backfill service_type onto such
artifacts to bring them fully under this model."* Once a capability is produced by `/v1/discover`
(§4 below), it carries a real `service_type` and this gap closes for it. Don't rely on "any
authenticated client can execute any legacy artifact" as permanent behavior — it's a
migration-era compatibility shim, not the target state.

**Note on local state:** the one real artifact this whole doc exercises,
`artifacts/lookup-member-savings-balance.v1.json`, is a tracked-but-mutable file — running §4's
live discover call (or just using this demo over time) will backfill its `service_type` and flip
its `lifecycle`, so §3.3's specific 200-success result depends on *when* it was captured. Check
`service_type` in that file directly if you want current ground truth rather than trusting this
doc's snapshot.

---

## 4. "New capability, no id" — discovery from a goal

A first-time caller doesn't know a `capability_id` yet — it supplies `service_type` +
`system_identifier` + a natural-language `goal`, and the resolver either reuses an existing
approved match or runs real Claude discovery.

**⚠️ Running this against your live server for real right now** will find no approved match
(the committed artifact's `service_type` is `null` — see §3.3), so it will make a **genuine,
billed Anthropic API call** and drive a real (non-headless) Chromium browser, and it will
**overwrite `artifacts/lookup-member-savings-balance.v1.json`** (same id/version) with a fresh
`draft` — flipping the tracked, currently-`approved` artifact back to `draft` until you
re-approve it. That's expected/by-design (it's the backfill path from §3.3), not a bug, but it
does modify a git-tracked file, so know that before you run it. `git checkout --
artifacts/lookup-member-savings-balance.v1.json` reverts it afterward if you don't want to keep
the change.

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:8000/v1/discover \
  -u demo-client:secret123 -H 'content-type: application/json' -d '{
    "service_type": "member_savings_balance_lookup",
    "system_identifier": "legacy-member-servicing-demo",
    "client_inquiry_id": "scenario-020",
    "goal": "Find member 10001 and return savings balance"
  }'
```

Real captured response (from an isolated run — see
`scripts/debug/discover_v1_flow.py`, which runs this exact call against a throwaway temp
directory instead of your real `artifacts/`, so you can watch this branch without the tracked-file
side effect above):

```json
{
  "capability_id": "lookup-member-savings-balance.v1",
  "inquiry_id": "43c89e44-0be0-4700-a3b3-3571c869cc0b",
  "reused_existing_capability": false,
  "lifecycle": "draft",
  "approval_required": true
}
```

`approval_required: true` is the explicit signal (alongside `lifecycle: "draft"`) that this isn't
invocable yet. Before approving, an admin can find and inspect it via the **admin approval
queue** — §6 below — rather than only learning it exists from this response. Approve it first
(§2.6/§2.4 style call, but with an admin credential):

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST \
  http://127.0.0.1:8000/v1/capabilities/lookup-member-savings-balance.v1/approve \
  -u demo-client:secret123
```

```json
{ "capability_id": "lookup-member-savings-balance.v1", "lifecycle": "approved" }
HTTP 200
```

### 4.1 Calling `/v1/discover` again with the same `(service_type, system_identifier)` — reuse

Once approved, a second call for the exact same pair — from `demo-client` or **any other**
authorized client — returns the same `capability_id` immediately, with **no Claude call**:

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:8000/v1/discover \
  -u demo-client:secret123 -H 'content-type: application/json' -d '{
    "service_type": "member_savings_balance_lookup",
    "system_identifier": "legacy-member-servicing-demo",
    "client_inquiry_id": "scenario-021",
    "goal": "Find member 10001 and return savings balance"
  }'
```

```json
{
  "capability_id": "lookup-member-savings-balance.v1",
  "inquiry_id": "1ea877f4-2c1c-493a-9c74-56082678955f",
  "reused_existing_capability": true,
  "lifecycle": "approved",
  "approval_required": false
}
HTTP 200
```

(Both real captured values, from the same isolated run used to capture §6 below.)

---

## 5. Human handoff and risky-action approval — for real, over curl

The committed `lookup-member-savings-balance.v1` can't exercise either of these on its own: its
steps are all `risk: "read_only"` and it has no pause `ErrorRule`. `tests/test_intervention.py`
and `tests/test_approval.py` prove both mechanisms by building a modified artifact *in memory*,
inside the test process — which is real coverage, but not something you can point a browser or
curl at. `scripts/debug/create_pause_demo_capability.py` and
`scripts/debug/create_approval_demo_capability.py` do the same modification, but **save the
result as a separate, real, invocable capability** (`lookup-member-savings-balance-pause-demo.v1`
/ `-approval-demo.v1`) — untracked local files, never touching the real approved artifact — so
both flows are drivable through the actual running server. Every response below is real,
captured live.

### 5.1 Human handoff: pause on an unexpected interstitial

`demo_app`'s member `10003` always renders a "Session Notice" interstitial (`demo_app/app.py`).
The pause-demo capability adds a `pause`-recovery `ErrorRule` targeting that text on the search
step. This one needs a **real manual click** to resolve — that's the point of "same-session
handoff": the live Playwright `Page` object stays open in-process (`InterventionManager._pages`,
`intervention/manager.py`), never part of any API response, so only something acting in the same
process — a human at the visible browser, or a test standing in for one — can act on it.

```bash
uv run python scripts/debug/create_pause_demo_capability.py   # once
```

```bash
# blocks until resumed — run in its own terminal
curl -s -X POST http://127.0.0.1:8000/capabilities/lookup-member-savings-balance-pause-demo.v1/execute \
  -H 'content-type: application/json' -d '{"inputs":{"memberId":"10003"}}'
```

While it's blocked, in another terminal:

```bash
curl -s http://127.0.0.1:8000/interventions
```

```json
{
  "id": "e91244f1-ede6-485f-8ba7-dfdc9c462716",
  "run_id": "efdf9fc9-8edd-45e7-8a8e-2eb982e90e42",
  "capability_id": "lookup-member-savings-balance-pause-demo.v1",
  "reason": "Unexpected session interstitial requires human dismissal",
  "step_id": "step-2",
  "screenshot": "evidence/runs/efdf9fc9-8edd-45e7-8a8e-2eb982e90e42/pause-step-2.png",
  "state": {
    "url": "http://127.0.0.1:8001/search",
    "accessibility": "- banner: MemberServ 7 - Internal Operations\n- main:\n  - alertdialog:\n    - paragraph: \"Session Notice: Please confirm to continue.\"\n    - button \"Continue\"\n  - heading \"Member Details\" [level=1]\n  ..."
  },
  "owner": "human",
  "approved": null,
  "created_at": "2026-09-16T20:12:13.489107Z"
}
```

The `screenshot` path is a real PNG on disk — open it, it shows the exact "Session Notice" dialog
with its "Continue" button. `GET /interventions` **never removes resolved entries**; use `owner`
to tell what's actually still pending (`"human"` = waiting, `"automation"` = already resumed).

Resolving without actually clicking "Continue" first fails hard rather than silently proceeding —
real captured proof:

```bash
curl -X POST http://127.0.0.1:8000/interventions/e91244f1-ede6-485f-8ba7-dfdc9c462716/resume
```

```json
{
  "status": "failure",
  "error": {
    "category": "checkpoint_failed",
    "code": "REPLAY_STEP_FAILED",
    "message": "Interruption at step 'step-2' was not resolved before resume — the condition is still present",
    "evidence_path": "evidence/runs/efdf9fc9-8edd-45e7-8a8e-2eb982e90e42/failure-step-2.png"
  }
}
```

To see it succeed, run the sequence again and this time actually click "Continue" in the visible
browser (this server runs `HEADLESS=false`, the repo default) before calling `.../resume` — the
blocked `execute` call returns `"status": "success", "outputs": {"savingsBalance": ...}`.

### 5.2 Risky-action approval gate — pending list, view, approve (no manual click needed)

This one is entirely curl-driven: nothing in the browser needs touching, since approving is a
yes/no decision, not a DOM interaction. The approval-demo capability marks one step (`step-3`,
"Open Accounts") `risk: "risky"` — above `config/policy.json`'s `maxRiskWithoutApproval`
(`"reversible"`).

```bash
uv run python scripts/debug/create_approval_demo_capability.py   # once
```

```bash
# "create" — blocks until resumed
curl -s -X POST http://127.0.0.1:8000/capabilities/lookup-member-savings-balance-approval-demo.v1/execute \
  -H 'content-type: application/json' -d '{"inputs":{"memberId":"10002"}}'
```

```bash
# "pending list" — same endpoint as §5.1; filter for owner: human
curl -s http://127.0.0.1:8000/interventions
```

```json
{
  "id": "ff179bef-caf1-4bbc-ae83-74d9e31bdaa8",
  "run_id": "294a595c-73e6-4fcd-9227-bafc951c659c",
  "capability_id": "lookup-member-savings-balance-approval-demo.v1",
  "reason": "Step 'step-3' is risky and requires human approval before it runs",
  "step_id": "step-3",
  "screenshot": "evidence/runs/294a595c-73e6-4fcd-9227-bafc951c659c/approval-step-3.png",
  "state": {
    "url": "http://127.0.0.1:8001/search",
    "accessibility": "- banner: MemberServ 7 - Internal Operations\n- main:\n  - heading \"Member Details\" [level=1]\n  ...\n  - button \"Open Accounts\""
  },
  "owner": "human",
  "approved": null,
  "created_at": "2026-09-16T20:56:24.516874Z"
}
```

The screenshot is the real "Member Details" page, right before the risky click — that's the
"view" step. Now approve it:

```bash
curl -X POST http://127.0.0.1:8000/interventions/ff179bef-caf1-4bbc-ae83-74d9e31bdaa8/resume \
  -H 'content-type: application/json' -d '{"approved": true}'
```

The blocked `execute` call from the first curl returns:

```json
{
  "status": "success",
  "capability_id": "lookup-member-savings-balance-approval-demo.v1",
  "outputs": { "savingsBalance": 1220.0 },
  "intervention_id": "ff179bef-caf1-4bbc-ae83-74d9e31bdaa8"
}
```

The approved click actually ran and the automation completed. Send `{"approved": false}` instead
to see the denial path: `category=policy, code=APPROVAL_DENIED`, matching
`tests/test_approval.py::test_denied_risky_step_fails_with_policy_error`.

Both `-pause-demo.v1` and `-approval-demo.v1` are throwaway local artifacts (`artifacts/*.json`,
untracked) — safe to regenerate any time by re-running their scripts.

---

## 6. Admin approval queue

Closing a real gap: `/v1/discover` can tell a *client* that something needs approval
(`approval_required: true`, §4), but until now there was no REST way for an *admin* to find out —
only local CLI filesystem access (`capability-platform list`) could see a draft. These two
admin-only endpoints add that visibility. The existing `POST /v1/capabilities/{id}/approve`
endpoint is unchanged — reviewing here and then calling that same endpoint *is* the workflow.

All responses below are real, captured from the same isolated run as §4/§4.1 above (one real
Claude discovery, then every scenario run against it before and after approval).

### 6.1 List pending capabilities (admin)

```bash
curl -s -w '\nHTTP %{http_code}\n' http://127.0.0.1:8000/v1/capabilities/pending \
  -u demo-client:secret123
```

```json
{
  "capabilities": [
    {
      "capability_id": "lookup-member-savings-balance.v1",
      "name": "Lookup member savings balance",
      "lifecycle": "draft",
      "service_type": "member_savings_balance_lookup",
      "system_identifier": "legacy-member-servicing-demo",
      "created_at": "2026-09-15T23:43:11.901269Z",
      "discovered_by": "anthropic:claude-sonnet-4-5 prompt=production.v1"
    }
  ]
}
HTTP 200
```

A summary/scannable queue only — no steps, no inputs/outputs. Only `draft` (or any other
not-yet-`approved`/`active` lifecycle) shows up here; once approved, the same capability drops
out of this list (see the empty-list capture at the end of §6.2).

### 6.2 Review a pending capability in full (admin)

```bash
curl -s -w '\nHTTP %{http_code}\n' \
  http://127.0.0.1:8000/v1/capabilities/does-not-exist.v1/review \
  -u demo-client:secret123
```

```json
{ "detail": "Capability not found" }
HTTP 404
```

```bash
curl -s -w '\nHTTP %{http_code}\n' \
  http://127.0.0.1:8000/v1/capabilities/lookup-member-savings-balance.v1/review \
  -u demo-client:secret123
```

```json
{
  "capability_id": "lookup-member-savings-balance.v1",
  "name": "Lookup member savings balance",
  "description": "Find a member in the legacy demo app and return the savings balance.",
  "lifecycle": "draft",
  "service_type": "member_savings_balance_lookup",
  "system_identifier": "legacy-member-servicing-demo",
  "application": {
    "vendor": "Interface Demo",
    "product": "Legacy Member Servicing",
    "base_url": "http://127.0.0.1:8001",
    "supported_versions": ["demo-v1"],
    "tenant_overrides": {}
  },
  "inputs": [
    { "name": "memberId", "type": "string", "description": "Demo member identifier", "required": true, "sensitive": false, "pattern": "^\\d{5}$" }
  ],
  "outputs": [
    { "name": "savingsBalance", "type": "number", "description": "Current savings balance", "sensitive": false }
  ],
  "steps": [
    {
      "id": "step-1", "action": "type",
      "description": "Enter member ID 10001 into the Member Number search field",
      "risk": "reversible",
      "target": { "primary": { "strategy": "label", "value": "Member Number", "name": null, "exact": true, "frame": null }, "fallbacks": [], "rationale": "Accessible semantic target selected during successful Claude discovery" },
      "value": "{{memberId}}", "output": null, "checkpoint": null, "errors": []
    },
    {
      "id": "step-2", "action": "click",
      "description": "Click the Search button to find member 10001",
      "risk": "read_only",
      "target": { "primary": { "strategy": "role", "value": "button", "name": "Search", "exact": true, "frame": null }, "fallbacks": [], "rationale": "Accessible semantic target selected during successful Claude discovery" },
      "value": null, "output": null, "checkpoint": null,
      "errors": [{ "code": "MEMBER_NOT_FOUND", "category": "business", "when": { "kind": "visible", "target": { "primary": { "strategy": "text", "value": "Member not found", "name": null, "exact": false, "frame": null }, "fallbacks": [], "rationale": "Explicit application business outcome" }, "expected": null, "timeout_ms": 10000 }, "message": "No member exists for the supplied identifier", "recovery": "return", "max_retries": 0 }]
    },
    {
      "id": "step-3", "action": "click",
      "description": "Click the Open Accounts button to view account details including savings balance",
      "risk": "read_only",
      "target": { "primary": { "strategy": "role", "value": "button", "name": "Open Accounts", "exact": true, "frame": null }, "fallbacks": [], "rationale": "Accessible semantic target selected during successful Claude discovery" },
      "value": null, "output": null, "checkpoint": null,
      "errors": [{ "code": "MEMBER_NOT_FOUND", "category": "business", "when": { "kind": "visible", "target": { "primary": { "strategy": "text", "value": "Member not found", "name": null, "exact": false, "frame": null }, "fallbacks": [], "rationale": "Explicit application business outcome" }, "expected": null, "timeout_ms": 10000 }, "message": "No member exists for the supplied identifier", "recovery": "return", "max_retries": 0 }]
    },
    {
      "id": "step-4", "action": "extract",
      "description": "Extract the savings balance from the Available Balance column for Primary Savings",
      "risk": "read_only",
      "target": { "primary": { "strategy": "xpath", "value": "//tr[td[contains(.,'Primary Savings')]]/td[2]", "name": null, "exact": true, "frame": null }, "fallbacks": [], "rationale": "Accessible semantic target selected during successful Claude discovery" },
      "value": null, "output": "savingsBalance", "checkpoint": null,
      "errors": [{ "code": "MEMBER_NOT_FOUND", "category": "business", "when": { "kind": "visible", "target": { "primary": { "strategy": "text", "value": "Member not found", "name": null, "exact": false, "frame": null }, "fallbacks": [], "rationale": "Explicit application business outcome" }, "expected": null, "timeout_ms": 10000 }, "message": "No member exists for the supplied identifier", "recovery": "return", "max_retries": 0 }]
    }
  ],
  "success": {
    "kind": "visible",
    "target": { "primary": { "strategy": "text", "value": "Savings Account", "name": null, "exact": false, "frame": null }, "fallbacks": [], "rationale": "Business-state heading confirms the accounts screen" },
    "expected": null, "timeout_ms": 10000
  },
  "created_at": "2026-09-15T23:43:11.901269Z",
  "discovered_by": "anthropic:claude-sonnet-4-5 prompt=production.v1",
  "tags": ["member", "savings", "balance", "computer-use"],
  "requested_by": [
    {
      "client_id": "demo-client",
      "goal": "Find member 10001 and return savings balance",
      "client_inquiry_id": "verify-req-001",
      "environment": "production",
      "created_at": "2026-09-15T23:43:11.976874Z"
    }
  ]
}
HTTP 200
```

This is *everything* Claude compiled — every `step`, its locator strategy and fallbacks, risk
level, and business-outcome `errors` — plus `requested_by`, joined from every `InquiryRecord`
that ever asked for this exact `capability_id` (client, their literal `goal` text, when). That
join is new: neither the artifact nor any inquiry record persisted `goal` before this — see
`InquiryRecord.goal` (`access/models.py`) and `JSONInquiryTracker.list()`
(`access/tracking.py`), threaded through from `discover_v1`'s `request.goal`
(`api/v1_routes.py`).

After approving (§4's `/approve` call, unchanged), the queue empties out:

```bash
curl -s -w '\nHTTP %{http_code}\n' http://127.0.0.1:8000/v1/capabilities/pending \
  -u demo-client:secret123
```

```json
{ "capabilities": [] }
HTTP 200
```

See §2.8/§2.9 for the non-admin-403 cases on both endpoints, and §7 for the same flow as a
condensed, sequential one-by-one walkthrough (including how to get something back into the queue
if the one real capability here is already `approved`).

### What's still a gap (deliberately not built here)

1. **No reject/deny path** — a draft can only move forward or sit in the queue forever; there's
   no `POST /v1/capabilities/{id}/reject`.
2. **No approval audit trail** — `approve_v1` still doesn't record *who* approved or *when*;
   left untouched deliberately.
3. **No push notification** — an admin still has to poll `/v1/capabilities/pending`; nothing
   fires when a new draft appears.
4. **No CLI parity** — `capability-platform pending` / `... review <id>` don't exist; REST-only
   for now. `capability-platform list` remains the CLI's only view into this data.

---

## 7. One-by-one walkthrough: pending → review → approve

§6 above groups the same two endpoints by scenario (admin vs. non-admin, found vs. not-found).
This section is the condensed version for actually running through live, one command at a time:
create something pending, list it, inspect it, approve it, confirm it's gone. Every response below
is real, captured from a live run against this repo's actual servers.

**Before you start:** if `lookup-member-savings-balance.v1` is already `approved` (likely, if
you've run any of §3/§4 before), a fresh `/v1/discover` call for the same
`(service_type, system_identifier)` pair will just **reuse** it (`reused_existing_capability:
true`, `approval_required: false`) — nothing lands in the queue. This demo is single-capability
(the artifact `id` is hardcoded in `ClaudeDiscoveryAgent.discover`, not derived from the request),
so there's no way to get a second, independent draft on the live server. The practical fix is to
reset the existing one back to `draft` directly, rather than paying for another real Claude call:

```bash
uv run python -c "
from pathlib import Path
from capability_platform.capabilities.store import ArtifactStore
store = ArtifactStore(Path('artifacts'))
artifact = store.load('lookup-member-savings-balance.v1')
artifact.lifecycle = 'draft'
store.save(artifact)
print('reset to draft')
"
```

This directly edits the tracked file `artifacts/lookup-member-savings-balance.v1.json` — the same
file every real `/v1/discover` run in this doc already mutates, so nothing new is at risk.
`git checkout -- artifacts/lookup-member-savings-balance.v1.json` restores committed state
afterward if you want to undo it.

### Step 1 — List the pending queue

```bash
curl -s -w '\nHTTP %{http_code}\n' http://127.0.0.1:8000/v1/capabilities/pending \
  -u demo-client:secret123
```

```json
{
  "capabilities": [
    {
      "capability_id": "lookup-member-savings-balance.v1",
      "name": "Lookup member savings balance",
      "lifecycle": "draft",
      "service_type": "member_savings_balance_lookup",
      "system_identifier": "legacy-member-servicing-demo",
      "created_at": "2026-09-15T23:19:58.003634Z",
      "discovered_by": "anthropic:claude-sonnet-4-5 prompt=production.v1"
    }
  ]
}
HTTP 200
```

### Step 2 — View the full review detail

```bash
curl -s -w '\nHTTP %{http_code}\n' \
  http://127.0.0.1:8000/v1/capabilities/lookup-member-savings-balance.v1/review \
  -u demo-client:secret123
```

Same full shape as §6.2 — `application`, `inputs`, `outputs`, every `steps` entry, `success`, and
`requested_by`. One real difference worth calling out: `requested_by` accumulates **every**
`InquiryRecord` ever recorded against this `capability_id`, across every discover/reuse call this
repo has ever made — it grows over time and is not reset by the lifecycle reset above (that only
touches the artifact, not `data/tracking/`). A live capture at this point in this repo's history
returned 12 entries; here's a representative excerpt rather than the full list:

```json
{
  "capability_id": "lookup-member-savings-balance.v1",
  "lifecycle": "draft",
  "requested_by": [
    { "client_id": "demo-client", "goal": null, "client_inquiry_id": "smoke-req-001", "environment": "production", "created_at": "2026-09-15T20:05:34.079254Z" },
    { "client_id": "no-access-client", "goal": null, "client_inquiry_id": "scenario-015", "environment": "production", "created_at": "2026-09-15T22:34:53.736604Z" },
    { "client_id": "demo-client", "goal": "Find member 10001 and return savings balance", "client_inquiry_id": "scenario-020", "environment": "production", "created_at": "2026-09-15T23:54:12.145189Z" },
    { "client_id": "demo-client", "goal": "Find member 10001 and return savings balance", "client_inquiry_id": "step-001", "environment": "production", "created_at": "2026-09-16T00:16:55.880885Z" }
  ]
}
HTTP 200
```

`goal: null` entries predate the `InquiryRecord.goal` field added for this feature — expected,
per its backward-compatible default (see §6's join explanation above).

### Step 3 — Approve it

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST \
  http://127.0.0.1:8000/v1/capabilities/lookup-member-savings-balance.v1/approve \
  -u demo-client:secret123
```

```json
{ "capability_id": "lookup-member-savings-balance.v1", "lifecycle": "approved" }
HTTP 200
```

### Step 4 — Confirm the queue is empty again

```bash
curl -s -w '\nHTTP %{http_code}\n' http://127.0.0.1:8000/v1/capabilities/pending \
  -u demo-client:secret123
```

```json
{ "capabilities": [] }
HTTP 200
```

Want to see the 403 path too? Swap `-u demo-client:secret123` for `-u viewer-client:viewer123` on
Step 1 or Step 2 before running the admin version — see §2.8/§2.9.

---

## 8. New demo-only endpoints

Two small additions purely for the local admin dashboard (`GET /admin`, see below) — not part of
the versioned `/v1` client contract, both unauthenticated like `/interventions` already is.

### 8.1 `GET /runs/{run_id}/events` — read back a run's evidence trace

```bash
curl -s "http://127.0.0.1:8000/runs/60b294fc-8963-4c2a-a630-5fa18b511517/events"
```

```json
{
  "run_id": "60b294fc-8963-4c2a-a630-5fa18b511517",
  "events": [
    {"timestamp": "...", "event": "replay.started", "capability": "lookup-member-savings-balance.v1", "inputs": {"memberId": "10002"}},
    {"timestamp": "...", "event": "step.started", "step_id": "step-1", "action": "type"},
    {"timestamp": "...", "event": "step.completed", "step_id": "step-1"},
    "... one started/completed pair per step ...",
    {"timestamp": "...", "event": "replay.completed", "status": "success"},
    {"timestamp": "...", "event": "replay.finished"}
  ]
}
HTTP 200
```

Reads `evidence/runs/{run_id}/events.jsonl`, already redacted at write-time by `Redactor.clean()`
(`observability/evidence.py`) — safe to render raw. Unknown `run_id` → 404. This is also how the
same-session `page_identity` proof (§5) gets pulled into the admin dashboard: the
`intervention.created` and `control.transferred owner=automation` events both carry it, and a
live check just confirmed them identical again —
`created.page_identity: 4507093264` / `after.page_identity: 4507093264` → match.

### 8.2 `POST /admin/seed-demo-capabilities` — one-click setup for the intervention demos

```bash
curl -s -X POST http://127.0.0.1:8000/admin/seed-demo-capabilities
```

```json
{ "seeded": ["lookup-member-savings-balance-pause-demo.v1", "lookup-member-savings-balance-approval-demo.v1"] }
HTTP 200
```

Equivalent to running both `scripts/debug/create_pause_demo_capability.py` and
`create_approval_demo_capability.py` by hand — both now share their artifact-construction logic
via `capabilities/demo_seed.py` (`build_pause_demo`/`build_approval_demo`). Idempotent — safe to
call more than once. 404s if the base `lookup-member-savings-balance.v1` doesn't exist yet (run
discovery once first).

### 8.3 `GET /admin` — the full dashboard

Everything in this document — discover, pending/review/approve, execute (success/business
outcome/failure), the intervention flows, the same-session proof, and the observability trace —
is now clickable in one page instead of curl. Open `http://127.0.0.1:8000/admin` once `make
platform` is running. Each section carries an "Implements:" note citing the exact file/function it
demonstrates.

---

## Appendix: full scenario index

| # | Scenario | Auth | Expected | Verified |
|---|---|---|---|---|
| 1.1 | List approved capabilities | none | 200 | ✅ live |
| 1.2 | Legacy execute, existing id, success | none | 200 `success` | ✅ live |
| 1.3 | Legacy execute, existing id, not found | none | 200 `business_outcome` | ✅ live |
| 1.4 | Legacy execute, unknown id | none | 404 | ✅ live |
| 2.1 | `/v1/discover`, no credentials | — | 401 | ✅ live |
| 2.2 | `/v1/discover`, wrong password | invalid | 401 | ✅ live |
| 2.3 | `/v1/discover`, unregistered client | invalid | 401 | ✅ live |
| 2.4 | `/v1/discover`, unauthorized `service_type` | valid, unauthorized | 403 | ✅ live |
| 2.5 | `/v1/discover`, unknown `system_identifier` | valid | 400 | ✅ live |
| 2.6 | `/v1/.../approve`, non-admin | valid, non-admin | 403 | ✅ live |
| 2.7 | `/v1/.../execute`, unknown id | valid | 404 | ✅ live |
| 2.8 | `/v1/capabilities/pending`, non-admin | valid, non-admin | 403 | ✅ isolated run |
| 2.9 | `/v1/.../review`, non-admin | valid, non-admin | 403 | ✅ isolated run |
| 3.1 | `/v1/.../execute`, existing id, success | valid, authorized | 200 `success` | ✅ live |
| 3.2 | `/v1/.../execute`, existing id, not found | valid, authorized | 200 `business_outcome` | ✅ live |
| 3.3 | `/v1/.../execute`, legacy artifact, unauthorized client | valid, unauthorized | 200 (gap — see §3.3) | ✅ live |
| 4 | `/v1/discover`, new capability, no id | valid, authorized | 200, `reused: false`, `draft`, `approval_required: true` | ✅ isolated run |
| 4 | `/v1/.../approve` the new draft | valid, admin | 200, `approved` | ✅ live |
| 4.1 | `/v1/discover`, same pair again | valid, authorized | 200, `reused: true`, `approval_required: false` | ✅ isolated run |
| 5.1 | Human handoff pause, resume without dismissing | none | 200 `failure`, `REPLAY_STEP_FAILED` | ✅ live |
| 5.1 | Human handoff pause, `GET /interventions` while paused | none | 200, `owner: human` | ✅ live |
| 5.2 | Risky-step approval, `GET /interventions` while paused | none | 200, `owner: human` | ✅ live |
| 5.2 | Risky-step approval, `resume` with `approved: true` | none | 200 `success`, step ran | ✅ live |
| 6.1 | `/v1/capabilities/pending`, admin | valid, admin | 200, one draft listed | ✅ isolated run |
| 6.2 | `/v1/.../review`, admin | valid, admin | 200, full detail + `requested_by` | ✅ isolated run |
| 6.2 | `/v1/.../review`, unknown id, admin | valid, admin | 404 | ✅ isolated run |
| 6 | `/v1/capabilities/pending` after approval | valid, admin | 200, empty list | ✅ isolated run |
| 7 | One-by-one: reset → pending → review → approve → empty | valid, admin | 200 at every step | ✅ live |
| 8.1 | `GET /runs/{run_id}/events` | none | 200, events list | ✅ live |
| 8.2 | `POST /admin/seed-demo-capabilities` | none | 200, both ids seeded | ✅ live |
