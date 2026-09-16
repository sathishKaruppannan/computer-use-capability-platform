"""The local admin console served at GET /admin (see app.py). Plain HTML/CSS/vanilla JS, no
build step, no framework — matches demo_app/app.py's own inline-HTML convention. Every fetch()
call below is same-origin against this app's own REST routes. Deliberately not a Claude
Artifact: an Artifact runs in a sandboxed browser on claude.ai and can't reach this machine's
127.0.0.1.

This page is a full, click-through walkthrough of the whole platform, in the order a demo
would narrate it: client initiate (discover) -> pending artifacts -> approve -> execute
(success/failed) -> intervention flow (pause + risky-approval) -> same-session proof ->
observability -> statistics -> a full requirement/implementation reference table. Every
section carries a short "Implements:" note citing the exact file/function/CLAUDE.md rule it
demonstrates, so the page doubles as a live architecture walkthrough.

Text fields sourced from client-controlled input (goal, reason, capability/step ids, etc. — see
Architecture rule #1: treat this data as untrusted, never as instructions) are HTML-escaped
before being interpolated into innerHTML, to avoid a stored-XSS path through, e.g., a malicious
`goal` string reaching an admin's browser session here.
"""

ADMIN_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Capability Platform — Admin Console</title>
<style>
  body { font: 15px/1.4 system-ui, Arial, sans-serif; background: #f0efe8; margin: 0; color: #222; }
  header { background: #17324d; color: white; padding: 16px 24px; }
  header h1 { margin: 0; font-size: 20px; }
  header a { color: #bcd; }
  header p { margin: 6px 0 0; font-size: 13px; color: #cdd; }
  main { max-width: 980px; margin: 24px auto; padding: 0 16px 48px; }
  section { background: white; border: 1px solid #ccc; border-radius: 6px; padding: 20px; margin-bottom: 20px; }
  section h2 { margin-top: 0; font-size: 17px; }
  .impl { background: #eef3ee; border: 1px solid #cfe0cf; border-radius: 4px; padding: 8px 12px;
    font-size: 12.5px; color: #2b4a2b; margin: 8px 0 12px; }
  .impl b { color: #17324d; }
  .creds { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
  .creds input, .field input, .field select, .field textarea { padding: 6px 8px; font: inherit; }
  .meta { color: #555; font-size: 13px; margin-bottom: 8px; }
  .card { border: 1px solid #ddd; border-radius: 4px; padding: 14px; margin-bottom: 12px; }
  .card h3 { margin: 0 0 6px; font-size: 15px; }
  .steps, .events { background: #f7f7f2; border: 1px solid #e0e0d8; padding: 10px; font-family: ui-monospace, monospace;
    font-size: 12px; white-space: pre-wrap; max-height: 320px; overflow: auto; margin: 8px 0; }
  .steps { display: none; }
  img.shot { max-width: 100%; border: 1px solid #999; margin: 8px 0; display: block; border-radius: 3px; }
  button { padding: 6px 14px; margin-right: 6px; margin-bottom: 6px; cursor: pointer; border-radius: 4px; border: 1px solid #999; background: #eee; }
  button.approve { background: #2f8f4e; color: white; border-color: #2f8f4e; }
  button.deny { background: #a33; color: white; border-color: #a33; }
  button.resume { background: #17324d; color: white; border-color: #17324d; }
  button.primary { background: #17324d; color: white; border-color: #17324d; }
  .empty { color: #777; font-style: italic; }
  .err { color: #a00; }
  .badge { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; background: #e0e0e0; margin-left: 6px; }
  .pill { display: inline-block; padding: 2px 10px; border-radius: 10px; font-size: 12px; font-weight: 600; color: white; }
  .pill.success { background: #2f8f4e; }
  .pill.business_outcome { background: #b8860b; }
  .pill.failure { background: #a33; }
  .pill.paused { background: #2a5da0; }
  .field { margin-bottom: 10px; }
  .field label { display: block; font-size: 12.5px; color: #444; margin-bottom: 2px; }
  .field input, .field select, .field textarea { width: 100%; box-sizing: border-box; }
  .row { display: flex; gap: 12px; flex-wrap: wrap; }
  .row .field { flex: 1; min-width: 180px; }
  .legend { font-size: 12.5px; color: #555; background: #f7f7f2; border: 1px solid #e0e0d8; border-radius: 4px; padding: 8px 10px; margin-bottom: 10px; }
  .proof { border: 1px solid #cfe0cf; background: #eef3ee; border-radius: 4px; padding: 10px 12px; margin: 8px 0; font-size: 13px; }
  .proof.mismatch { background: #fbeaea; border-color: #e0b8b8; }
  table.stats { border-collapse: collapse; width: 100%; }
  table.stats td, table.stats th { border: 1px solid #ddd; padding: 8px 10px; text-align: left; font-size: 13px; }
  .tiles { display: flex; gap: 12px; flex-wrap: wrap; }
  .tile { background: #f7f7f2; border: 1px solid #e0e0d8; border-radius: 6px; padding: 12px 16px; min-width: 120px; }
  .tile .n { font-size: 24px; font-weight: 700; color: #17324d; }
  .tile .l { font-size: 12px; color: #666; }
  details.ref summary { cursor: pointer; font-weight: 600; }
  table.ref { border-collapse: collapse; width: 100%; margin-top: 10px; }
  table.ref td, table.ref th { border: 1px solid #ddd; padding: 6px 8px; font-size: 12px; vertical-align: top; }
  nav.toc { font-size: 13px; }
  nav.toc a { margin-right: 10px; }
</style>
</head>
<body>
<header>
  <h1>Capability Platform — Admin Console</h1>
  <p>Claude discovers a UI flow once via Playwright; <code>ReplayEngine</code> replays it deterministically
    afterward with zero LLM calls. Test app: <a href="http://127.0.0.1:8001" target="_blank">http://127.0.0.1:8001</a></p>
</header>
<main>

  <section id="overview">
    <h2>How to read this page</h2>
    <p class="meta">Each section below is one real REST call (or a client-side combination of a few), in the order a
      live demo would narrate them. Condensed from <code>docs/ARCHITECTURE_WALKTHROUGH.md</code>'s "Suggested demo
      script."</p>
    <nav class="toc">
      <a href="#client-initiate">1. Client initiate</a>
      <a href="#pending-capabilities">2. Pending artifacts</a>
      <a href="#all-artifacts">3. All artifacts</a>
      <a href="#execute">4. Execute</a>
      <a href="#intervention-seed">5. Intervention setup</a>
      <a href="#pending-interventions">6. Interventions + same-session proof</a>
      <a href="#observability">7. Observability</a>
      <a href="#statistics">8. Statistics</a>
      <a href="#reference">9. Full reference</a>
    </nav>
  </section>

  <section id="credentials">
    <h2>Credentials</h2>
    <div class="creds">
      <input id="client-id" placeholder="client_id" value="demo-client">
      <input id="password" type="password" placeholder="password" value="secret123">
      <button onclick="refreshAll()">Refresh everything</button>
      <label><input type="checkbox" id="auto-refresh" onchange="toggleAuto()"> auto-refresh (5s)</label>
    </div>
    <p class="meta">HTTP Basic, same scheme as <code>curl -u</code> — used by every <code>/v1/...</code> call below
      (Client initiate, Pending artifacts, All artifacts, /v1 Execute). Held in page memory only.</p>
  </section>

  <section id="client-initiate">
    <h2>1. Client initiate <span class="badge">POST /v1/discover</span></h2>
    <div class="impl"><b>Implements:</b> <code>discover_v1()</code> (<code>api/v1_routes.py</code>) — the resolver
      <code>ArtifactStore.find_approved_by_service_and_system()</code> checks for an existing approved match first;
      on a miss, <code>ClaudeDiscoveryAgent.discover()</code> (<code>agent/discovery.py</code>) drives a real
      Playwright browser with Claude deciding each step. <b>This is the only button on the whole page that opens a
      browser and calls Claude</b> — everything else below replays deterministically or just reads data. A fresh
      discover's artifact defaults to <code>lifecycle: "draft"</code>, so this one button also covers "create
      artifacts" and "create pending artifacts."</div>
    <div class="row">
      <div class="field"><label>service_type</label>
        <select id="ci-service-type"><option value="member_savings_balance_lookup">member_savings_balance_lookup</option></select></div>
      <div class="field"><label>system_identifier</label>
        <input id="ci-system-identifier" value="legacy-member-servicing-demo"></div>
    </div>
    <div class="field"><label>goal</label>
      <input id="ci-goal" value="Find member 10001 and return savings balance"></div>
    <div class="row">
      <div class="field"><label>example_member_id</label><input id="ci-member-id" value="10001"></div>
      <div class="field"><label>client_inquiry_id (auto)</label><input id="ci-inquiry-id" readonly></div>
    </div>
    <button class="primary" onclick="submitDiscover()">Run discover</button>
    <p id="ci-status" class="meta"></p>
    <div class="events" id="ci-result" style="display:none"></div>
    <p class="meta">Already approved and matches the pair above? "Run discover" will just <b>reuse</b> it (correct
      behavior, not a bug — no new draft, no Claude call). To demo the approve flow (§2) again without spending a
      real ~30-60s Claude call every time, reset it back to <code>draft</code> instead:</p>
    <div class="row">
      <div class="field"><label>capability_id to reset</label><input id="rd-capability-id" value="lookup-member-savings-balance.v1"></div>
    </div>
    <button onclick="resetToDraft()">Reset to draft (no Claude call, instant)</button>
    <p id="rd-status" class="meta"></p>
  </section>

  <section id="pending-capabilities">
    <h2>2. Pending artifacts — client approval flow <span id="cap-count" class="badge"></span></h2>
    <div class="impl"><b>Implements:</b> <code>GET /v1/capabilities/pending</code> (<code>list_pending_capabilities_v1</code>)
      and <code>GET /v1/capabilities/{id}/review</code> (<code>review_capability_v1</code> — note the
      <code>requested_by</code> join against <code>JSONInquiryTracker.list()</code>, showing who asked and their
      literal goal), then <code>POST /v1/capabilities/{id}/approve</code> — flips <code>lifecycle</code> to
      <code>"approved"</code>. Architecture rule #2: approval is a human/credential decision, independent of the
      model.</div>
    <div id="capabilities"><p class="empty">Loading…</p></div>
  </section>

  <section id="all-artifacts">
    <h2>3. All artifacts <span id="all-count" class="badge"></span></h2>
    <div class="impl"><b>Implements:</b> <code>GET /capabilities</code> (approved/active,
      <code>ArtifactStore.list_approved()</code>) merged client-side with the pending list above
      (<code>ArtifactStore.list()</code>, filtered). No third "list everything" endpoint was added — this table is
      two existing calls combined in JS, per the minimal-change constraint.</div>
    <div id="all-artifacts"><p class="empty">Loading…</p></div>
  </section>

  <section id="execute">
    <h2>4. Execute — success / failed flow</h2>
    <div class="impl"><b>Implements:</b> <code>ReplayEngine.execute()</code> (<code>computer_use/replay.py</code>) —
      deterministic Playwright replay, zero LLM calls (proven by
      <code>tests/test_replay_e2e.py::test_replay_never_instantiates_llm_client</code>). Distinguishes
      <code>RunStatus.SUCCESS</code> / <code>BUSINESS_OUTCOME</code> / <code>FAILURE</code> (rule #6) — never a
      free-text pass/fail.</div>
    <div class="legend">Demo member ids (<code>demo_app/app.py</code>): <b>10001, 10002</b> → success ·
      <b>10003</b> → pause intervention · <b>10004</b> → automated wait/retry (no human) ·
      <b>10005</b> → session-expired hard failure · <b>99999</b>/unknown → business outcome, member not found.</div>
    <div class="row">
      <div class="field"><label>capability_id</label><input id="ex-capability-id" value="lookup-member-savings-balance.v1"></div>
      <div class="field"><label>memberId</label><input id="ex-member-id" value="10002"></div>
      <div class="field"><label>client_inquiry_id (auto, /v1 only)</label><input id="ex-inquiry-id" readonly></div>
    </div>
    <button onclick="submitExecute(false)">Execute (legacy, no auth)</button>
    <button onclick="submitExecute(true)">Execute (/v1, authenticated)</button>
    <p id="ex-status" class="meta"></p>
    <div id="ex-pill"></div>
    <div class="events" id="ex-result" style="display:none"></div>
  </section>

  <section id="intervention-seed">
    <h2>5. Intervention flow — one-click setup <span class="badge">POST /admin/seed-demo-capabilities</span></h2>
    <div class="impl"><b>Implements:</b> the real approved artifact's steps are all
      <code>risk: "read_only"</code> and has no pause rule, so neither intervention kind is reachable on it. This
      endpoint builds two separate demo capabilities (<code>capabilities/demo_seed.py</code>:
      <code>build_pause_demo</code> injects a <code>pause</code>-recovery <code>ErrorRule</code>;
      <code>build_approval_demo</code> marks one step <code>RiskLevel.RISKY</code>) so both
      <code>Intervention.kind</code> values (<code>"pause"</code> vs <code>"approval"</code>,
      <code>intervention/manager.py</code>) are demoable without touching the real capability.</div>
    <button class="primary" onclick="seedDemoCapabilities()">Seed demo capabilities</button>
    <p id="seed-status" class="meta"></p>
    <div id="seed-shortcuts"></div>
  </section>

  <section id="pending-interventions">
    <h2>6. Pending interventions — approve / resume <span id="int-count" class="badge"></span></h2>
    <div class="impl"><b>Implements:</b> <code>GET /interventions?pending=true</code> (filters to
      <code>owner: "human"</code>) and <code>POST /interventions/{id}/resume</code> →
      <code>InterventionManager.resume()</code>. <b>Same-session proof:</b> <code>computer_use/replay.py</code> logs
      <code>page_identity = id(surface.page)</code> — CPython's object identity for the live Playwright
      <code>Page</code> — into the evidence trail at pause and again after resume. Identical value on both sides
      proves the exact same in-process browser session was reused, not a new one substituted in.</div>
    <p class="meta">Resolved entries stay in the full audit trail (<code>GET /interventions</code>, no filter) but
      drop off this filtered view.</p>
    <div id="interventions"><p class="empty">Loading…</p></div>
  </section>

  <section id="observability">
    <h2>7. Observability — events for a run</h2>
    <div class="impl"><b>Implements:</b> new <code>GET /runs/{run_id}/events</code>, reading
      <code>evidence/runs/{run_id}/events.jsonl</code> written by <code>EvidenceCollector.event()</code>
      (<code>observability/evidence.py</code>) — every field already redacted at write time by
      <code>Redactor.clean()</code> (SSN/authorization/api-key/cookie/session-id/password patterns, rule #3), so
      it's safe to render raw here.</div>
    <div class="field"><label>run_id</label><input id="ob-run-id" placeholder="paste or auto-filled from Execute/Interventions above"></div>
    <button onclick="loadObservability()">Load events</button>
    <div class="events" id="ob-result" style="display:none"></div>
  </section>

  <section id="statistics">
    <h2>8. Statistics</h2>
    <div class="impl"><b>Implements:</b> nothing new server-side — pure client-side aggregation over data already
      returned by the sections above (<code>ArtifactStore.list()</code>/<code>list_approved()</code>,
      <code>InterventionManager.items</code> via existing endpoints). No <code>/stats</code> endpoint exists.</div>
    <div class="tiles" id="stats-tiles"></div>
  </section>

  <section id="reference">
    <details class="ref">
      <summary>9. Full requirement ↔ implementation reference table</summary>
      <table class="ref">
        <tr><th>Requirement</th><th>Demoed in</th><th>File / function</th><th>Engine / note</th></tr>
        <tr><td>Test app</td><td>header link</td><td><code>demo_app/app.py</code></td><td>standalone FastAPI app, the automation target</td></tr>
        <tr><td>Client initiate (REST, auth)</td><td>§1</td><td><code>v1_routes.py:discover_v1</code></td><td>HTTP Basic via <code>api/auth.py</code></td></tr>
        <tr><td>Create / pending artifacts</td><td>§1</td><td><code>CapabilityArtifact.lifecycle</code> default <code>"draft"</code></td><td>no LLM call on a reuse hit</td></tr>
        <tr><td>Client approval flow</td><td>§2</td><td><code>v1_routes.py:approve_v1</code></td><td>admin-gated, independent of the model (rule #2)</td></tr>
        <tr><td>Success / failed flow</td><td>§4</td><td><code>computer_use/replay.py:ReplayEngine.execute</code></td><td>Playwright, deterministic, zero LLM</td></tr>
        <tr><td>Intervention flow</td><td>§5 + §6</td><td><code>capabilities/demo_seed.py</code>, <code>replay.py</code></td><td>pause vs. risky-approval, same mechanism</td></tr>
        <tr><td>Pending intervention / view list</td><td>§6</td><td><code>app.py:list_interventions</code></td><td><code>owner == HUMAN</code> filter</td></tr>
        <tr><td>View list of artifacts</td><td>§3</td><td><code>ArtifactStore.list_approved</code> + <code>.list</code></td><td>client-side merge, no new endpoint</td></tr>
        <tr><td>Approve artifacts</td><td>§2</td><td><code>v1_routes.py:approve_v1</code></td><td>unchanged existing endpoint</td></tr>
        <tr><td>Same session continue</td><td>§6</td><td><code>replay.py</code> <code>page_identity</code></td><td><code>id(surface.page)</code>, in-process handoff</td></tr>
        <tr><td>View observability events</td><td>§7</td><td><code>app.py:run_events</code>, <code>observability/evidence.py</code></td><td>redacted JSONL trace</td></tr>
        <tr><td>Statistics / dashboard</td><td>§8</td><td>client-side JS only</td><td>no backend change</td></tr>
      </table>
    </details>
  </section>

</main>

<script>
const state = { lastCapabilityId: null, lastRunId: null, lastInquiryId: null, allArtifacts: [] };

function esc(s) {
  const d = document.createElement('div');
  d.textContent = (s === null || s === undefined) ? '' : String(s);
  return d.innerHTML;
}

function authHeader() {
  const id = document.getElementById('client-id').value;
  const pw = document.getElementById('password').value;
  return 'Basic ' + btoa(id + ':' + pw);
}

function cssSafe(s) { return s.replace(/[^a-zA-Z0-9]/g, '_'); }

function newInquiryId() {
  return (crypto.randomUUID ? crypto.randomUUID() : 'inq-' + Date.now() + '-' + Math.random().toString(16).slice(2));
}

// ---------- §1 Client initiate ----------

function primeInquiryIds() {
  document.getElementById('ci-inquiry-id').value = newInquiryId();
  document.getElementById('ex-inquiry-id').value = newInquiryId();
}

async function submitDiscover() {
  const status = document.getElementById('ci-status');
  const box = document.getElementById('ci-result');
  status.textContent = 'Running discovery… this may take up to a minute and opens a visible browser.';
  box.style.display = 'none';
  try {
    const body = {
      service_type: document.getElementById('ci-service-type').value,
      system_identifier: document.getElementById('ci-system-identifier').value,
      client_inquiry_id: document.getElementById('ci-inquiry-id').value,
      goal: document.getElementById('ci-goal').value,
      example_member_id: document.getElementById('ci-member-id').value,
    };
    const res = await fetch('/v1/discover', {
      method: 'POST',
      headers: { 'Authorization': authHeader(), 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    box.style.display = 'block';
    box.textContent = JSON.stringify(data, null, 2);
    if (!res.ok) { status.textContent = `Failed: HTTP ${res.status}`; return; }
    state.lastCapabilityId = data.capability_id;
    document.getElementById('ex-capability-id').value = data.capability_id;
    status.textContent = data.reused_existing_capability
      ? 'reused_existing_capability = true → reused an existing approved capability, zero LLM calls.'
      : 'reused_existing_capability = false → brand-new draft/pending artifact created. See §2 below to review + approve it.';
    primeInquiryIds();
    refreshAll();
  } catch (e) {
    status.textContent = 'Error: ' + esc(e);
  }
}

async function resetToDraft() {
  const status = document.getElementById('rd-status');
  const capId = document.getElementById('rd-capability-id').value;
  status.textContent = 'Resetting…';
  try {
    const res = await fetch(`/admin/reset-to-draft/${encodeURIComponent(capId)}`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) { status.textContent = `Failed: ${data.detail || res.status}`; return; }
    status.textContent = `${data.capability_id} is now "${data.lifecycle}" — see §2 Pending artifacts below.`;
    refreshAll();
  } catch (e) { status.textContent = 'Error: ' + esc(e); }
}

// ---------- §2 Pending capabilities (existing) ----------

async function loadCapabilities() {
  const el = document.getElementById('capabilities');
  try {
    const res = await fetch('/v1/capabilities/pending', { headers: { 'Authorization': authHeader() } });
    const data = await res.json();
    if (!res.ok) { el.innerHTML = `<p class="err">${res.status}: ${esc(data.detail || 'error')}</p>`; return; }
    document.getElementById('cap-count').textContent = data.capabilities.length;
    if (data.capabilities.length === 0) { el.innerHTML = '<p class="empty">Nothing pending.</p>'; return; }
    el.innerHTML = data.capabilities.map(c => `
      <div class="card">
        <h3>${esc(c.capability_id)}</h3>
        <div class="meta">${esc(c.name)} · ${esc(c.service_type || '(no service_type)')} ·
          ${esc(c.system_identifier || '(no system)')} · ${esc(c.lifecycle)} · discovered by ${esc(c.discovered_by)}</div>
        <div class="steps" id="review-${cssSafe(c.capability_id)}"></div>
        <button onclick="reviewCapability('${esc(c.capability_id)}')">View details</button>
        <button class="approve" onclick="approveCapability('${esc(c.capability_id)}')">Approve</button>
      </div>`).join('');
  } catch (e) { el.innerHTML = `<p class="err">${esc(e)}</p>`; }
}

async function reviewCapability(id) {
  const box = document.getElementById('review-' + cssSafe(id));
  if (box.style.display === 'block') { box.style.display = 'none'; return; }
  const res = await fetch(`/v1/capabilities/${encodeURIComponent(id)}/review`, { headers: { 'Authorization': authHeader() } });
  const data = await res.json();
  if (!res.ok) { box.textContent = JSON.stringify(data); box.style.display = 'block'; return; }
  const steps = data.steps.map(s => `${s.id} ${s.action} (${s.risk}) — ${s.description}`).join('\\n');
  const who = data.requested_by.map(r => `${r.client_id}: "${r.goal || '(no goal recorded)'}" @ ${r.created_at}`).join('\\n');
  box.textContent = `STEPS:\\n${steps}\\n\\nREQUESTED BY:\\n${who || '(no inquiry history found)'}`;
  box.style.display = 'block';
}

async function approveCapability(id) {
  const res = await fetch(`/v1/capabilities/${encodeURIComponent(id)}/approve`, {
    method: 'POST', headers: { 'Authorization': authHeader() },
  });
  if (!res.ok) { alert(`Approve failed: ${res.status}`); }
  refreshAll();
}

// ---------- §3 All artifacts (client-side merge) ----------

async function loadAllArtifacts() {
  const el = document.getElementById('all-artifacts');
  const rows = [];
  try {
    const approvedRes = await fetch('/capabilities');
    const approved = await approvedRes.json();
    for (const c of approved) rows.push({ capability_id: c.id, name: c.name, lifecycle: 'approved/active', service_type: '', system_identifier: '' });
  } catch (e) { /* fall through, still try pending */ }
  let pendingNote = '';
  try {
    const pendingRes = await fetch('/v1/capabilities/pending', { headers: { 'Authorization': authHeader() } });
    const pendingData = await pendingRes.json();
    if (pendingRes.ok) {
      for (const c of pendingData.capabilities) rows.push({
        capability_id: c.capability_id, name: c.name, lifecycle: c.lifecycle,
        service_type: c.service_type || '', system_identifier: c.system_identifier || '',
      });
    } else {
      pendingNote = '<p class="meta">Sign in as an admin above to also see pending/draft artifacts.</p>';
    }
  } catch (e) { /* ignore */ }
  state.allArtifacts = rows;
  document.getElementById('all-count').textContent = rows.length;
  if (rows.length === 0) { el.innerHTML = '<p class="empty">No artifacts yet — run §1 Client initiate first.</p>'; return; }
  el.innerHTML = pendingNote + `<table class="stats"><tr><th>id</th><th>name</th><th>lifecycle</th><th>service_type</th><th>system_identifier</th></tr>` +
    rows.map(r => `<tr><td>${esc(r.capability_id)}</td><td>${esc(r.name)}</td><td>${esc(r.lifecycle)}</td><td>${esc(r.service_type)}</td><td>${esc(r.system_identifier)}</td></tr>`).join('') +
    `</table>`;
}

// ---------- §4 Execute ----------

async function submitExecute(useV1) {
  const status = document.getElementById('ex-status');
  const pill = document.getElementById('ex-pill');
  const box = document.getElementById('ex-result');
  const capId = document.getElementById('ex-capability-id').value;
  const memberId = document.getElementById('ex-member-id').value;
  status.textContent = (useV1 ? 'Calling POST /v1/capabilities/{id}/execute… ' : 'Calling POST /capabilities/{id}/execute… ')
    + 'If this capability has a risky/pause step (e.g. the seeded demo capabilities from §5), the browser will '
    + 'pause and this call will hang until you resolve it in §6 Pending interventions below — that\\'s expected, '
    + 'not stuck. Double-check the capability_id above if you didn\\'t mean to trigger that.';
  pill.innerHTML = '';
  box.style.display = 'none';
  try {
    let res;
    if (useV1) {
      res = await fetch(`/v1/capabilities/${encodeURIComponent(capId)}/execute`, {
        method: 'POST',
        headers: { 'Authorization': authHeader(), 'content-type': 'application/json' },
        body: JSON.stringify({ client_inquiry_id: document.getElementById('ex-inquiry-id').value, inputs: { memberId } }),
      });
    } else {
      res = await fetch(`/capabilities/${encodeURIComponent(capId)}/execute`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ inputs: { memberId } }),
      });
    }
    const data = await res.json();
    box.style.display = 'block';
    box.textContent = JSON.stringify(data, null, 2);
    if (!res.ok) { status.textContent = `Failed: HTTP ${res.status}`; return; }
    if (data.status) pill.innerHTML = `<span class="pill ${esc(data.status)}">${esc(data.status)}</span>`;
    if (data.run_id) {
      state.lastRunId = data.run_id;
      document.getElementById('ob-run-id').value = data.run_id;
    }
    status.textContent = data.intervention_id
      ? 'An intervention was created — see §6 Pending interventions below.'
      : 'Done. See §7 Observability for the full event trace of this run.';
    document.getElementById('ex-inquiry-id').value = newInquiryId();
    refreshAll();
  } catch (e) { status.textContent = 'Error: ' + esc(e); }
}

// ---------- §5 Intervention setup ----------

async function seedDemoCapabilities() {
  const status = document.getElementById('seed-status');
  const shortcuts = document.getElementById('seed-shortcuts');
  status.textContent = 'Seeding…';
  try {
    const res = await fetch('/admin/seed-demo-capabilities', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) { status.textContent = `Failed: ${data.detail || res.status}`; return; }
    status.textContent = 'Seeded: ' + data.seeded.join(', ');
    shortcuts.innerHTML = `
      <button onclick="fillExecute('${esc(data.seeded[0])}', '10003')">Use pause-demo (member 10003) in §4 Execute</button>
      <button onclick="fillExecute('${esc(data.seeded[1])}', '10002')">Use approval-demo (member 10002) in §4 Execute</button>`;
  } catch (e) { status.textContent = 'Error: ' + esc(e); }
}

function fillExecute(capId, memberId) {
  document.getElementById('ex-capability-id').value = capId;
  document.getElementById('ex-member-id').value = memberId;
  document.getElementById('execute').scrollIntoView({ behavior: 'smooth' });
}

// ---------- §6 Pending interventions + same-session proof ----------

async function loadInterventions() {
  const el = document.getElementById('interventions');
  try {
    const res = await fetch('/interventions?pending=true');
    const items = await res.json();
    document.getElementById('int-count').textContent = items.length;
    if (items.length === 0) { el.innerHTML = '<p class="empty">Nothing pending.</p>'; return; }
    el.innerHTML = items.map(i => `
      <div class="card">
        <h3>${esc(i.reason)}</h3>
        <div class="meta">capability: ${esc(i.capability_id || '(none)')} · step: ${esc(i.step_id || '(none)')} ·
          kind: ${esc(i.kind)} · run_id: ${esc(i.run_id)} · created: ${esc(i.created_at)}</div>
        ${i.screenshot ? `<img class="shot" src="/interventions/${encodeURIComponent(i.id)}/screenshot">` : ''}
        <div id="proof-${cssSafe(i.id)}"></div>
        ${i.kind === 'approval'
          ? `<button class="approve" onclick="resumeIntervention('${esc(i.id)}', true, '${esc(i.run_id)}')">Approve</button>
             <button class="deny" onclick="resumeIntervention('${esc(i.id)}', false, '${esc(i.run_id)}')">Deny</button>`
          : `<button class="resume" onclick="resumeIntervention('${esc(i.id)}', null, '${esc(i.run_id)}')">Resume</button>`}
      </div>`).join('');
  } catch (e) { el.innerHTML = `<p class="err">${esc(e)}</p>`; }
}

async function resumeIntervention(id, approved, runId) {
  const opts = { method: 'POST' };
  if (approved !== null) {
    opts.headers = { 'content-type': 'application/json' };
    opts.body = JSON.stringify({ approved });
  }
  const res = await fetch(`/interventions/${encodeURIComponent(id)}/resume`, opts);
  if (!res.ok) { alert(`Resume failed: ${res.status}`); return; }
  document.getElementById('ob-run-id').value = runId;
  state.lastRunId = runId;
  await showSessionProof(runId, id);
  refreshAll();
}

async function showSessionProof(runId, interventionId) {
  const target = document.getElementById('proof-' + cssSafe(interventionId));
  try {
    const res = await fetch(`/runs/${encodeURIComponent(runId)}/events`);
    const data = await res.json();
    if (!res.ok || !target) return;
    const events = data.events || [];
    const created = events.find(e => e.event === 'intervention.created');
    const after = events.find(e => e.event === 'control.transferred' && e.owner === 'automation')
      || events.find(e => e.event === 'resume.observed');
    if (!created || !after || created.page_identity === undefined) return;
    const match = created.page_identity === after.page_identity;
    target.innerHTML = `<div class="proof ${match ? '' : 'mismatch'}">
      Same-session proof — page_identity before: <code>${esc(created.page_identity)}</code>,
      after resume: <code>${esc(after.page_identity)}</code> →
      ${match ? '✓ identical, same Playwright session' : '✗ mismatch'}</div>`;
  } catch (e) { /* best-effort */ }
}

// ---------- §7 Observability ----------

async function loadObservability() {
  const runId = document.getElementById('ob-run-id').value.trim();
  const box = document.getElementById('ob-result');
  box.style.display = 'block';
  if (!runId) { box.textContent = 'Enter a run_id above (or run Execute / an intervention first).'; return; }
  try {
    const res = await fetch(`/runs/${encodeURIComponent(runId)}/events`);
    const data = await res.json();
    if (!res.ok) { box.textContent = `${res.status}: ${data.detail || 'error'}`; return; }
    box.textContent = data.events.map(e => {
      const rest = Object.fromEntries(Object.entries(e).filter(([k]) => k !== 'timestamp' && k !== 'event'));
      return `[${e.timestamp}] ${e.event} ${JSON.stringify(rest)}`;
    }).join('\\n');
  } catch (e) { box.textContent = 'Error: ' + esc(e); }
}

// ---------- §8 Statistics (client-side aggregation only) ----------

async function updateStatistics() {
  const el = document.getElementById('stats-tiles');
  const byLifecycle = {};
  for (const a of state.allArtifacts) byLifecycle[a.lifecycle] = (byLifecycle[a.lifecycle] || 0) + 1;

  let byKind = null, byOwner = null, totalInterventions = null;
  try {
    const res = await fetch('/interventions');
    const items = await res.json();
    byKind = {}; byOwner = {};
    for (const i of items) {
      byKind[i.kind] = (byKind[i.kind] || 0) + 1;
      byOwner[i.owner] = (byOwner[i.owner] || 0) + 1;
    }
    totalInterventions = items.length;
  } catch (e) { /* leave as — */ }

  const tile = (label, value) => `<div class="tile"><div class="n">${value === null || value === undefined ? '—' : esc(value)}</div><div class="l">${esc(label)}</div></div>`;
  let html = tile('Total artifacts', state.allArtifacts.length || (state.allArtifacts.length === 0 ? 0 : '—'));
  for (const [k, v] of Object.entries(byLifecycle)) html += tile('lifecycle: ' + k, v);
  html += tile('Total interventions (ever)', totalInterventions);
  if (byKind) for (const [k, v] of Object.entries(byKind)) html += tile('kind: ' + k, v);
  if (byOwner) for (const [k, v] of Object.entries(byOwner)) html += tile('owner: ' + k, v);
  el.innerHTML = html;
}

// ---------- shared ----------

function refreshAll() {
  loadCapabilities();
  loadAllArtifacts().then(updateStatistics);
  loadInterventions();
}

let autoTimer = null;
function toggleAuto() {
  clearInterval(autoTimer);
  if (document.getElementById('auto-refresh').checked) {
    autoTimer = setInterval(refreshAll, 5000);
  }
}

primeInquiryIds();
refreshAll();
</script>
</body>
</html>
"""
