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
  .chat-log { background: #f7f7f2; border: 1px solid #e0e0d8; border-radius: 6px; padding: 12px; margin: 10px 0;
    max-height: 420px; overflow: auto; display: flex; flex-direction: column; gap: 10px; }
  .bubble { max-width: 80%; padding: 8px 12px; border-radius: 10px; font-size: 13.5px; white-space: pre-wrap; }
  .bubble.user { align-self: flex-end; background: #17324d; color: white; border-bottom-right-radius: 2px; }
  .bubble.assistant { align-self: flex-start; background: white; border: 1px solid #ddd; border-bottom-left-radius: 2px; }
  .bubble.assistant.refused { border-color: #e0b8b8; background: #fbeaea; }
  .bubble.assistant.error { border-color: #e0b8b8; background: #fbeaea; }
  .bubble .stage-tag { display: block; font-size: 11px; color: #888; margin-top: 4px; }
  .chat-row { display: flex; gap: 8px; }
  .chat-row textarea { flex: 1; padding: 8px; font: inherit; resize: vertical; min-height: 42px; box-sizing: border-box; }
  .examples { display: none; }
  .examples.open { display: block; }
  .ex-item { border: 1px solid #ddd; border-radius: 4px; padding: 8px 10px; margin-bottom: 8px; cursor: pointer; background: #fbfbf7; }
  .ex-item:hover { background: #eef3ee; border-color: #b9d0b9; }
  .ex-item .ex-goal { font-weight: 600; font-size: 13px; }
  .ex-item .ex-note { font-size: 12px; color: #666; margin-top: 2px; }
  .toggle-link { font-size: 13px; color: #17324d; cursor: pointer; text-decoration: underline; user-select: none; }
  .trace { display: none; }
  .trace.open { display: block; }
  .trace-item { border-left: 3px solid #ccc; padding: 4px 0 4px 10px; margin-bottom: 4px; font-size: 12.5px; }
  .trace-item.ok { border-left-color: #2f8f4e; }
  .trace-item.fail { border-left-color: #a33; }
  .trace-item.info { border-left-color: #2a5da0; }
  .trace-item .t-label { font-weight: 600; }
  .trace-item .t-detail { color: #555; white-space: pre-wrap; word-break: break-word; }
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
      <a href="#chatbot">0. Try a goal</a>
      <a href="#client-initiate">1. Client initiate</a>
      <a href="#test-app">Test app</a>
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

  <section id="chatbot">
    <h2>0. Try a goal <span class="badge">POST /agent/execute</span></h2>
    <div class="impl"><b>Implements:</b> <code>AgentOrchestrator.execute_goal()</code>
      (<code>agent/orchestrator.py</code>) end to end — <code>IntentAnalyzer</code> (LLM) →
      <code>Planner</code> → <code>PlanValidator</code> → <code>CapabilityResolver</code> → execution
      (existing typed artifact replay, or a discovery fallback) → deterministic aggregation →
      <code>GroundedSynthesizer.synthesize_agent_result()</code>. This is the single entry point the rest
      of this page's §1–§8 exercise piece by piece — type a goal below the way an end user would, with no
      knowledge of capability ids, and it pulls whatever it needs (intent, plan, matching capability,
      stored credentials, service type) itself.</div>
    <p class="meta">Uses the same client_id/password above. Optional target URL only matters if this goal
      needs a brand-new capability discovered (no existing match) — see the examples below.</p>
    <div id="chat-log" class="chat-log"></div>
    <div class="chat-row">
      <textarea id="chat-goal" placeholder="e.g. Find member 10001 and return savings balance"></textarea>
      <button class="primary" id="chat-send-btn" onclick="sendChatGoal()">Send</button>
    </div>
    <div class="field" style="margin-top:8px">
      <label><input type="checkbox" id="chat-show-advanced" onchange="toggleChatAdvanced()"> Advanced (target URL / context)</label>
    </div>
    <div class="row" id="chat-advanced" style="display:none">
      <div class="field"><label>target_url (optional)</label><input id="chat-target-url" placeholder="http://127.0.0.1:8001/secure"></div>
    </div>
    <p id="chat-status" class="meta"></p>

    <p><span class="toggle-link" onclick="toggleExamples()" id="examples-toggle">▸ Show example goals (one per scenario, for demo reference)</span></p>
    <div class="examples" id="examples-box"></div>

    <p><span class="toggle-link" onclick="toggleTrace()" id="trace-toggle">▸ Show what's happening behind the scenes (last run's trace)</span></p>
    <div class="trace" id="trace-box"><p class="empty">Send a goal above to see its step-by-step trace here.</p></div>
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
      artifacts" and "create pending artifacts." <b>How credentials find the right field:</b> there's no
      field-name matching on our side — Claude reads the page and matches each named credential to a labeled
      input itself, the same way it already finds the "Member Number" box; our code only supplies the
      name/value pairs via the goal hint. <code>auth_type</code> just changes which named values that is:
      <code>username</code>/<code>password</code>, or a single <code>apiKey</code> — same mechanism either
      way (<code>ClaudeDiscoveryAgent._credential_input_specs</code>).</div>
    <div class="field"><label>Target resource type</label>
      <select id="ci-resource-type" onchange="onResourceTypeChange()">
        <option value="url">URL (web)</option>
        <option value="exe">Executable (.exe)</option>
        <option value="iframe">URL with iFrame</option>
        <option value="other">Other surface (custom)</option>
      </select></div>
    <p class="impl" id="ci-resource-type-note" style="display:none">
      <b>Not implemented for this demo.</b> Only <code>URL (web)</code> is functional here — discovery drives a real
      Playwright browser against a web page. The other options are shown to illustrate where this platform is
      designed to grow: every surface-specific action (click, type, screenshot, read) already sits behind one
      abstraction, <code>SurfaceAdapter</code> (<code>computer_use/surface.py</code>), and <code>PlaywrightSurface</code>
      is its only implementation today. A desktop <code>.exe</code> or an embedded iframe target would plug in as a
      second <code>SurfaceAdapter</code> implementation — same discovery/replay engine, same artifact format, no
      planner changes — rather than a rewrite. Select <code>URL (web)</code> to use this demo.</p>
    <div id="ci-url-fields">
    <div class="row">
      <div class="field"><label>service_type</label>
        <select id="ci-service-type"><option value="member_savings_balance_lookup">member_savings_balance_lookup</option></select></div>
      <div class="field" id="ci-system-field"><label>system_identifier</label>
        <select id="ci-system-identifier" onchange="onSystemChange()"></select>
        <p class="meta" id="ci-system-url"></p></div>
    </div>
    <div class="field"><label><input type="checkbox" id="ci-use-direct-url" onchange="onUseDirectUrlChange()">
      Use a direct URL instead (skip the system registry)</label></div>
    <div class="row" id="ci-direct-url-fields" style="display:none">
      <div class="field"><label>target_url</label><input id="ci-target-url" placeholder="http://127.0.0.1:8001/secure"></div>
      <div class="field"><label>system_identifier (any label — reuse/artifact-id key, not registry-checked)</label>
        <input id="ci-direct-system-identifier" placeholder="my-direct-target"></div>
    </div>
    <div class="field"><label>goal</label>
      <input id="ci-goal" value="Find member 10001 and return savings balance"></div>
    <div class="field"><label><input type="checkbox" id="ci-auth-required" onchange="onAuthRequiredChange()"> Requires login?</label>
      <p class="meta">Checking this auto-selects the matching <code>-secure</code> system below, if one exists — the
        resolver doesn't otherwise check that your target actually has a login page. <b>If that system is already
        approved from an earlier run, "Run discover" will just reuse it and skip discovery entirely</b> — check
        "Force re-discover" below too if you specifically want to watch it run again live.</p></div>
    <div id="ci-auth-fields" style="display:none">
      <div class="field"><label>auth_type</label>
        <select id="ci-auth-type" onchange="onAuthTypeChange()">
          <option value="credentials">Username &amp; Password</option>
          <option value="api_key">API Key</option>
        </select></div>
      <div class="row" id="ci-credentials-fields">
        <div class="field"><label>example_username</label><input id="ci-username" value="demo"></div>
        <div class="field"><label>example_password</label><input id="ci-password" type="password" value="letmein-2024"></div>
      </div>
      <div class="row" id="ci-apikey-fields" style="display:none">
        <div class="field"><label>example_api_key</label><input id="ci-api-key" placeholder="sk-demo-..."></div>
      </div>
    </div>
    <div class="field"><label><input type="checkbox" id="ci-force-rediscover">
      Force re-discover (update existing capability with a fresh LLM pass)</label></div>
    <div class="row">
      <div class="field"><label>example_member_id</label><input id="ci-member-id" value="10001"></div>
      <div class="field"><label>client_inquiry_id (auto)</label><input id="ci-inquiry-id" readonly></div>
    </div>
    <button class="primary" id="ci-run-discover-btn" onclick="submitDiscover()">Run discover</button>
    <p id="ci-status" class="meta"></p>
    <div class="impl" id="ci-progress" style="display:none">
      <b>Live discovery progress</b> — each step as Claude decides it (action, locator strategy/value, why):
      <div class="events" id="ci-progress-events"></div>
    </div>
    <div class="events" id="ci-result" style="display:none"></div>
    </div>
    <p class="meta">Already approved and matches the pair above? "Run discover" will just <b>reuse</b> it (correct
      behavior, not a bug — no new draft, no Claude call). To demo the approve flow (§2) again without spending a
      real ~30-60s Claude call every time, reset it back to <code>draft</code> instead — pick from every artifact
      this console currently knows about (list refreshes automatically as you use the page, or click "Refresh
      everything" above):</p>
    <div class="row">
      <div class="field"><label>capability to reset</label><select id="rd-capability-id"></select></div>
    </div>
    <button onclick="resetToDraft()">Reset to draft (no Claude call, instant)</button>
    <p id="rd-status" class="meta"></p>

    <div class="impl" style="margin-top:18px"><b>Implements:</b> <code>POST /v1/capabilities/{id}/credentials</code>
      (<code>save_credentials_v1</code>) — works on a still-<code>draft</code> capability exactly as well as an
      already-<code>approved</code> one (storing credentials never grants execution access on its own; only an
      approved/active capability can actually run, checked separately at every execute path). Repeatable on
      purpose: re-running this for the same <code>(capability_id, client_id)</code> pair overwrites the stored
      value, so different usernames/passwords can be tried against the same capability as many times as needed,
      without re-approving anything each time.</div>
    <p class="meta">Save (or update/retest) login credentials for one client, on any capability — draft or
      approved:</p>
    <div class="row">
      <div class="field"><label>capability</label><select id="cred-capability-id"></select></div>
      <div class="field"><label>client_id</label><input id="cred-client-id" value="demo-client"></div>
    </div>
    <div class="row">
      <div class="field"><label>username</label><input id="cred-username" value="demo"></div>
      <div class="field"><label>password</label><input id="cred-password" type="password" value="letmein-2024"></div>
    </div>
    <button onclick="saveCredentials()">Save credentials</button>
    <p id="cred-status" class="meta"></p>
  </section>

  <section id="test-app">
    <h2>Test app <span class="badge">preview only</span></h2>
    <div class="impl"><b>Implements:</b> nothing — this is a manual preview iframe of the target demo app's own
      pages (<code>demo_app/app.py</code>), so you can see what Claude will see before running discovery.
      <b>This is NOT a live view of the separate Playwright-controlled automation browser window</b> — discovery
      opens its own independent, non-headless browser context entirely outside this page; the iframe below and
      that automation browser are two different browser sessions with no connection to each other.</div>
    <iframe src="http://127.0.0.1:8001" style="width:100%;height:420px;border:1px solid #ccc"></iframe>
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
        <tr><td>Test app</td><td>header link + dedicated iframe section</td><td><code>demo_app/app.py</code></td><td>standalone FastAPI app, the automation target — including <code>/secure/*</code>, the login-gated area</td></tr>
        <tr><td>Auth-required discovery, log in and continue</td><td>§1 ("Requires login?")</td><td><code>agent/discovery.py:discover</code>, <code>demo_app/app.py</code> <code>/secure/*</code></td><td>Claude finds the login form itself; credentials templated as <code>{{username}}</code>/<code>{{password}}</code>, never baked into the artifact</td></tr>
        <tr><td>Recreate / update via fresh LLM pass</td><td>§1 ("Force re-discover")</td><td><code>v1_routes.py:discover_v1</code> <code>force_rediscover</code></td><td>bypasses the reuse check; <code>ArtifactStore.save()</code> overwrites in place</td></tr>
        <tr><td>Show URL / direct-URL discovery</td><td>§1 (system picker + "Use a direct URL")</td><td><code>v1_routes.py</code> <code>GET /v1/systems</code>, <code>target_url</code></td><td><code>PolicyEngine.authorize_url()</code> still enforced either way</td></tr>
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
        <tr><td>Natural-language goal entry (chatbot)</td><td>§0</td><td><code>api/agent_routes.py:execute_agent</code>, <code>agent/orchestrator.py:execute_goal</code></td><td>full Intent → Plan → Resolve → Execute → Synthesize pipeline</td></tr>
        <tr><td>Per-client credential storage / reuse across clients</td><td>§0 examples + §2 approve dialog</td><td><code>access/tenant_credentials.py</code>, <code>v1_routes.py:approve_v1</code>/<code>save_credentials_v1</code></td><td>keyed by (capability_id, client_id); executor auto-pulls at run time</td></tr>
        <tr><td>Ambiguous-goal clarification guardrail</td><td>§0 examples</td><td><code>TaskIntent.requires_clarification</code>, <code>orchestrator.py:_intent_plan_resolve</code></td><td>refused before planning, never guessed at</td></tr>
        <tr><td>Sensitive-info guardrail</td><td>§0 examples</td><td><code>TaskIntent.requests_sensitive_info</code>, <code>SensitiveInfoRequestedError</code></td><td>same redaction category as <code>observability/evidence.py</code>'s <code>Redactor</code></td></tr>
        <tr><td>Step-by-step "what's happening" trace</td><td>§0 trace panel</td><td><code>app.py:run_events</code> + client-side <code>friendlyEvent()</code></td><td>relabels the real evidence event stream, no new backend data</td></tr>
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

// ---------- §0 Chatbot ----------

const EXAMPLE_GOALS = [
  { category: 'Existing capability match — reused instantly, zero LLM planning surprises',
    goal: 'Find member 10001 and return savings balance',
    note: 'Matches the approved lookup-member-savings-balance.v1 capability directly. Try member 10002/10003/10004/10005/99999 too — see §4\\'s legend for what each demo member id does.' },
  { category: 'Goal + target URL — brand-new capability, discovered live',
    goal: 'Look up the account status for member 10001',
    targetUrl: 'http://127.0.0.1:8001',
    note: 'No existing capability produces "account status" — this falls back to live Claude discovery against the given URL and returns "a new capability draft has been created... ask your admin to review and approve it." Takes up to ~60s and opens a visible browser.' },
  { category: 'Login-gated capability — credentials pulled automatically at execution',
    goal: 'Find member 10002 and return savings balance from the secure member portal',
    note: 'Only resolves to a login-gated capability if one has been discovered + approved (§1, check "Requires login?") and this client has credentials stored for it (§2 approve dialog, or POST /v1/capabilities/{id}/credentials). Otherwise you\\'ll see the "credentials needed, ask your admin" failure below — also a valid demo point.' },
  { category: 'Ambiguous goal — clarification guardrail',
    goal: 'Handle this member.',
    note: 'No discernible entity/operation/action — the Intent Analyzer itself flags requires_clarification instead of guessing, and the orchestrator refuses to plan for it.' },
  { category: 'Sensitive-info request — refused outright, never partially answered',
    goal: "What is member 10002's full Social Security Number?",
    note: 'Regulated/secret data category (full SSN, password/API key, session/cookie value, unmasked account number) — refused before any plan/resolution attempt, same redaction category as the evidence Redactor.' },
  { category: 'Unknown / unresolvable goal — still a clean, typed response',
    goal: 'Reticulate the splines for member 10001',
    note: 'Not ambiguous (has a verb/subject), but nothing in the capability catalog remotely matches it — falls back to discovery, which will fail to find anything on the demo app and returns a proper failure response instead of a crash or a hallucinated answer.' },
];

function renderExamples() {
  const box = document.getElementById('examples-box');
  box.innerHTML = EXAMPLE_GOALS.map((ex, i) => `
    <div class="ex-item" onclick="useExample(${i})">
      <div class="ex-goal">${esc(ex.goal)}</div>
      <div class="ex-note"><b>${esc(ex.category)}.</b> ${esc(ex.note)}${ex.targetUrl ? ' target_url: <code>' + esc(ex.targetUrl) + '</code>' : ''}</div>
    </div>`).join('');
}

function useExample(i) {
  const ex = EXAMPLE_GOALS[i];
  document.getElementById('chat-goal').value = ex.goal;
  if (ex.targetUrl) {
    document.getElementById('chat-show-advanced').checked = true;
    toggleChatAdvanced();
    document.getElementById('chat-target-url').value = ex.targetUrl;
  }
  document.getElementById('chatbot').scrollIntoView({ behavior: 'smooth' });
}

function toggleExamples() {
  const box = document.getElementById('examples-box');
  const link = document.getElementById('examples-toggle');
  const open = box.classList.toggle('open');
  link.textContent = (open ? '▾ Hide' : '▸ Show') + ' example goals (one per scenario, for demo reference)';
}

function toggleTrace() {
  const box = document.getElementById('trace-box');
  const link = document.getElementById('trace-toggle');
  const open = box.classList.toggle('open');
  link.textContent = (open ? '▾ Hide' : '▸ Show') + " what's happening behind the scenes (last run's trace)";
}

function toggleChatAdvanced() {
  document.getElementById('chat-advanced').style.display =
    document.getElementById('chat-show-advanced').checked ? 'flex' : 'none';
}

function addChatBubble(role, text, extraClass) {
  const log = document.getElementById('chat-log');
  const div = document.createElement('div');
  div.className = 'bubble ' + role + (extraClass ? ' ' + extraClass : '');
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

async function sendChatGoal() {
  const goalEl = document.getElementById('chat-goal');
  const goal = goalEl.value.trim();
  if (!goal) return;
  const status = document.getElementById('chat-status');
  const sendBtn = document.getElementById('chat-send-btn');
  const targetUrl = document.getElementById('chat-target-url').value.trim();
  const runId = newInquiryId();

  addChatBubble('user', goal);
  goalEl.value = '';
  sendBtn.disabled = true;
  status.textContent = 'Working… intent analysis, planning, capability resolution' +
    (targetUrl ? ', possibly live discovery against the target URL' : '') + '. This can take a few seconds, longer if a new capability needs discovering.';

  try {
    const body = { goal, client_inquiry_id: newInquiryId(), run_id: runId, context: {} };
    if (targetUrl) body.target_url = targetUrl;
    const res = await fetch('/agent/execute', {
      method: 'POST',
      headers: { 'Authorization': authHeader(), 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      addChatBubble('assistant', data.detail || `Request failed (HTTP ${res.status})`, 'refused');
      status.textContent = `HTTP ${res.status} — see the bubble above. The trace panel below still shows what ran before the refusal.`;
    } else {
      const summary = data.result || {};
      addChatBubble('assistant', summary.synthesized_text || '(no response text)');
      status.textContent = `status=${summary.status} · run_id=${data.run_id} — see the trace panel below for the full step-by-step pipeline.`;
      document.getElementById('ob-run-id').value = data.run_id;
      state.lastRunId = data.run_id;
      refreshAll();
    }
  } catch (e) {
    addChatBubble('assistant', 'Error: ' + e, 'error');
    status.textContent = 'Request failed before a response was received.';
  } finally {
    sendBtn.disabled = false;
  }
  await loadTrace(runId);
  const traceBox = document.getElementById('trace-box');
  if (!traceBox.classList.contains('open')) toggleTrace();
}

function friendlyEvent(e) {
  switch (e.event) {
    case 'intent.analyzed': {
      const intent = e.intent || {};
      return { label: 'LLM called → intent identified', kind: 'ok',
        detail: `intent=${intent.intent} · domain=${intent.domain} · operation=${intent.operation} · risk=${intent.risk} · confidence=${intent.confidence} · provider=${e.provider}` };
    }
    case 'intent.clarification_required':
      return { label: 'Guardrail: ambiguous goal → clarification required', kind: 'fail', detail: e.question };
    case 'guardrail.sensitive_info_refused':
      return { label: 'Guardrail: sensitive-info request refused', kind: 'fail', detail: e.reason };
    case 'plan.created':
      return { label: 'Orchestration → plan created', kind: 'ok', detail: `${e.step_count} step(s): ${(e.steps || []).join(', ')}` };
    case 'plan.validated':
      return { label: 'Plan validated against policy', kind: 'ok',
        detail: (e.steps_requiring_approval || []).length ? `Requires human approval: ${e.steps_requiring_approval.join(', ')}` : 'No steps require approval' };
    case 'capability.candidates_retrieved':
      return { label: `Capability candidates retrieved (${e.step_id})`, kind: 'info',
        detail: `${e.candidate_count} candidate(s): ${(e.candidate_ids || []).join(', ') || '(none found)'}` };
    case 'capability.selected':
      return { label: `Capability selected (${e.step_id})`, kind: 'ok', detail: `${e.descriptor_id} · score=${e.final_score}` };
    case 'capability.rejected':
      return { label: `No existing capability matched (${e.step_id}) → will fall back to discovery`, kind: 'info', detail: e.reason };
    case 'discovery.fallback_started':
      return { label: 'Discover call started — no existing artifact matched', kind: 'info', detail: e.discovery_goal };
    case 'discovery.observed':
      return { label: `Discovery — page observed (step ${e.step})`, kind: 'info', detail: '' };
    case 'discovery.decided': {
      const d = e.decision || {};
      return { label: `Discovery — Claude decided the next action (step ${e.step})`, kind: 'info',
        detail: `${d.action} — ${d.strategy ? d.strategy + '=' + (d.value || d.name || '') + ' — ' : ''}${d.reason || ''}` };
    }
    case 'discovery.acted':
      return { label: `Discovery — action performed (${e.step_id})`, kind: 'info', detail: e.action };
    case 'discovery.completed':
      return { label: 'Discovery completed → draft artifact created (needs admin approval)', kind: 'ok', detail: e.artifact };
    case 'capability.executed':
      return { label: `Capability executed (${e.step_id})`, kind: /FAILURE/.test(e.status) ? 'fail' : 'ok', detail: `${e.descriptor_id} → ${e.status}` };
    case 'replay.started':
      return { label: 'Replay started — typed artifact, zero LLM calls', kind: 'info', detail: e.capability };
    case 'step.started':
      return { label: `Replay step started (${e.step_id})`, kind: 'info', detail: e.action };
    case 'step.completed':
      return { label: `Replay step completed (${e.step_id})`, kind: 'ok', detail: '' };
    case 'business_outcome':
      return { label: `Business outcome reached (${e.step_id})`, kind: 'info', detail: e.code };
    case 'validation.failed':
      return { label: 'Postcondition/checkpoint validation failed', kind: 'fail', detail: JSON.stringify(e.error || {}) };
    case 'intervention.created':
      return { label: 'Paused for human intervention', kind: 'info', detail: e.reason || '' };
    case 'control.transferred':
      return { label: `Control transferred to ${e.owner}`, kind: 'info', detail: '' };
    case 'resume.validated':
      return { label: `Resume validated (${e.step_id})`, kind: 'ok', detail: '' };
    case 'replay.completed':
      return { label: 'Replay completed', kind: 'ok', detail: JSON.stringify(e.outputs || {}) };
    case 'result.aggregated':
      return { label: 'Outputs aggregated — deterministic, exact-key lookups only, no LLM', kind: 'ok', detail: JSON.stringify(e.outputs || {}) };
    case 'result.synthesized':
      return { label: 'Response synthesized — grounded in canonical outputs, no LLM in this step', kind: 'ok', detail: e.text };
    default:
      return { label: e.event, kind: 'info', detail: '' };
  }
}

async function loadTrace(runId) {
  const box = document.getElementById('trace-box');
  try {
    const res = await fetch(`/runs/${encodeURIComponent(runId)}/events`);
    if (!res.ok) { box.innerHTML = '<p class="empty">No evidence found for this run.</p>'; return; }
    const data = await res.json();
    const events = data.events || [];
    if (events.length === 0) { box.innerHTML = '<p class="empty">No events recorded for this run.</p>'; return; }
    box.innerHTML = `<p class="meta">Real evidence events for run_id=${esc(runId)} (GET /runs/{run_id}/events), relabeled for readability — nothing here is fabricated client-side.</p>` +
      events.map(e => {
        const f = friendlyEvent(e);
        return `<div class="trace-item ${f.kind}"><span class="t-label">${esc(f.label)}</span>` +
          (f.detail ? `<div class="t-detail">${esc(f.detail)}</div>` : '') + `</div>`;
      }).join('');
  } catch (e) {
    box.innerHTML = `<p class="err">${esc(e)}</p>`;
  }
}

document.getElementById('chat-goal').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatGoal(); }
});
renderExamples();

// ---------- §1 Client initiate ----------

function primeInquiryIds() {
  document.getElementById('ci-inquiry-id').value = newInquiryId();
  document.getElementById('ex-inquiry-id').value = newInquiryId();
}

async function loadSystems() {
  try {
    const res = await fetch('/v1/systems');
    const data = await res.json();
    const sel = document.getElementById('ci-system-identifier');
    sel.innerHTML = data.systems.map(s =>
      `<option value="${esc(s.system_identifier)}" data-url="${esc(s.base_url)}">${esc(s.system_identifier)} — ${esc(s.base_url)}</option>`
    ).join('');
    onSystemChange();
  } catch (e) { /* best-effort; system picker just stays empty */ }
}

function onSystemChange() {
  const sel = document.getElementById('ci-system-identifier');
  const opt = sel.options[sel.selectedIndex];
  document.getElementById('ci-system-url').textContent = opt ? `Target URL: ${opt.dataset.url}` : '';
}

function onResourceTypeChange() {
  const isUrl = document.getElementById('ci-resource-type').value === 'url';
  document.getElementById('ci-url-fields').style.display = isUrl ? 'block' : 'none';
  document.getElementById('ci-resource-type-note').style.display = isUrl ? 'none' : 'block';
}

function onUseDirectUrlChange() {
  const useDirect = document.getElementById('ci-use-direct-url').checked;
  document.getElementById('ci-system-field').style.display = useDirect ? 'none' : 'block';
  document.getElementById('ci-direct-url-fields').style.display = useDirect ? 'flex' : 'none';
}

function onAuthRequiredChange() {
  const checked = document.getElementById('ci-auth-required').checked;
  document.getElementById('ci-auth-fields').style.display = checked ? 'block' : 'none';
  if (checked && !document.getElementById('ci-use-direct-url').checked) {
    // Convenience: the resolver doesn't check whether the selected system actually has a login
    // page, so auto-pick the matching "-secure" one if it exists, rather than silently
    // discovering against a target with no login form to find.
    const sel = document.getElementById('ci-system-identifier');
    const secureOpt = Array.from(sel.options).find(o => o.value.endsWith('-secure'));
    if (secureOpt) { sel.value = secureOpt.value; onSystemChange(); }
  }
}

function onAuthTypeChange() {
  const isApiKey = document.getElementById('ci-auth-type').value === 'api_key';
  document.getElementById('ci-credentials-fields').style.display = isApiKey ? 'none' : 'flex';
  document.getElementById('ci-apikey-fields').style.display = isApiKey ? 'flex' : 'none';
}

let progressTimer = null;

function startProgressPolling(runId) {
  document.getElementById('ci-progress').style.display = 'block';
  document.getElementById('ci-progress-events').textContent = 'waiting for discovery to start…';
  const poll = async () => {
    try {
      const res = await fetch(`/runs/${encodeURIComponent(runId)}/events`);
      if (!res.ok) return;  // not created yet, or nothing to show -- try again next tick
      const data = await res.json();
      renderProgressEvents(data.events || []);
    } catch (e) { /* keep polling */ }
  };
  poll();
  progressTimer = setInterval(poll, 1500);
}

async function stopProgressPolling(runId) {
  clearInterval(progressTimer);
  progressTimer = null;
  if (runId) {
    try {
      const res = await fetch(`/runs/${encodeURIComponent(runId)}/events`);
      if (res.ok) renderProgressEvents((await res.json()).events || []);
    } catch (e) { /* final poll is best-effort */ }
  }
}

function renderProgressEvents(events) {
  const decided = events.filter(e => e.event === 'discovery.decided');
  if (decided.length === 0) {
    document.getElementById('ci-progress-events').textContent = 'waiting for the first step…';
    return;
  }
  document.getElementById('ci-progress-events').textContent = decided.map((e, i) => {
    const d = e.decision || {};
    const locator = d.strategy ? `${d.strategy}=${d.value || d.name || ''}` : '(no locator)';
    return `Step ${i + 1}: ${d.action} — ${locator} — ${d.reason || ''}`;
  }).join('\\n');
}

async function submitDiscover() {
  const status = document.getElementById('ci-status');
  const box = document.getElementById('ci-result');
  const useDirectUrl = document.getElementById('ci-use-direct-url').checked;
  const authRequired = document.getElementById('ci-auth-required').checked;
  const discoveryRunId = newInquiryId();
  status.textContent = 'Running discovery… this may take up to a minute and opens a visible browser.';
  box.style.display = 'none';
  startProgressPolling(discoveryRunId);
  try {
    const body = {
      service_type: document.getElementById('ci-service-type').value,
      system_identifier: useDirectUrl
        ? document.getElementById('ci-direct-system-identifier').value
        : document.getElementById('ci-system-identifier').value,
      client_inquiry_id: document.getElementById('ci-inquiry-id').value,
      goal: document.getElementById('ci-goal').value,
      example_member_id: document.getElementById('ci-member-id').value,
      is_auth_required: authRequired,
      force_rediscover: document.getElementById('ci-force-rediscover').checked,
      discovery_run_id: discoveryRunId,
    };
    if (useDirectUrl) body.target_url = document.getElementById('ci-target-url').value;
    if (authRequired) {
      const authType = document.getElementById('ci-auth-type').value;
      body.auth_type = authType;
      if (authType === 'api_key') {
        body.example_api_key = document.getElementById('ci-api-key').value;
      } else {
        body.example_username = document.getElementById('ci-username').value;
        body.example_password = document.getElementById('ci-password').value;
      }
    }
    const res = await fetch('/v1/discover', {
      method: 'POST',
      headers: { 'Authorization': authHeader(), 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    await stopProgressPolling(discoveryRunId);
    box.style.display = 'block';
    box.textContent = JSON.stringify(data, null, 2);
    if (!res.ok) {
      status.textContent = `Failed: HTTP ${res.status}`;
      document.getElementById('ci-progress-events').textContent = 'Failed before any discovery ran — see the response below.';
      return;
    }
    state.lastCapabilityId = data.capability_id;
    document.getElementById('ex-capability-id').value = data.capability_id;
    document.getElementById('ob-run-id').value = discoveryRunId;
    if (data.reused_existing_capability) {
      // On a reuse, discover_v1() never calls discover() at all -- no evidence run directory
      // is ever created for discoveryRunId, so the progress panel would otherwise be stuck on
      // "waiting for discovery to start..." forever with no explanation. Make the reuse itself
      // the visible result instead of leaving that message hanging.
      document.getElementById('ci-progress-events').textContent =
        'Reused an existing approved capability for this (service_type, system_identifier) pair — no discovery ran, so there is nothing to show here. Check "Force re-discover" above to force a fresh run instead.';
      status.textContent = 'reused_existing_capability = true → reused an existing approved capability, zero LLM calls.';
    } else {
      status.textContent = 'reused_existing_capability = false → brand-new draft/pending artifact created. See §2 below to review + approve it.';
    }
    primeInquiryIds();
    refreshAll();
  } catch (e) {
    await stopProgressPolling(discoveryRunId);
    status.textContent = 'Error: ' + esc(e);
  }
}

async function resetToDraft() {
  const status = document.getElementById('rd-status');
  const capId = document.getElementById('rd-capability-id').value;
  if (!capId) { status.textContent = 'No capability selected — click "Refresh everything" above first.'; return; }
  status.textContent = 'Resetting…';
  try {
    const res = await fetch(`/admin/reset-to-draft/${encodeURIComponent(capId)}`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) { status.textContent = `Failed: ${data.detail || res.status}`; return; }
    status.textContent = `${data.capability_id} is now "${data.lifecycle}" — see §2 Pending artifacts below.`;
    refreshAll();
  } catch (e) { status.textContent = 'Error: ' + esc(e); }
}

// Shared by the "reset to draft" and "save credentials" pickers -- both need "every capability
// this console currently knows about", refreshed on the same cadence as §3 All artifacts.
// Preserves each dropdown's current selection across a refresh where the option still exists,
// so re-testing the same capability repeatedly doesn't require re-picking it every time.
function populateCapabilityDropdowns() {
  const optionsHtml = state.allArtifacts.map(a =>
    `<option value="${esc(a.capability_id)}">${esc(a.capability_id)} (${esc(a.lifecycle)})</option>`
  ).join('');
  for (const id of ['rd-capability-id', 'cred-capability-id']) {
    const select = document.getElementById(id);
    if (!select) continue;
    const previous = select.value;
    select.innerHTML = optionsHtml;
    if (Array.from(select.options).some(o => o.value === previous)) select.value = previous;
  }
}

async function saveCredentials() {
  const status = document.getElementById('cred-status');
  const capId = document.getElementById('cred-capability-id').value;
  if (!capId) { status.textContent = 'No capability selected — click "Refresh everything" above first.'; return; }
  status.textContent = 'Saving…';
  try {
    const res = await fetch(`/v1/capabilities/${encodeURIComponent(capId)}/credentials`, {
      method: 'POST',
      headers: { 'Authorization': authHeader(), 'content-type': 'application/json' },
      body: JSON.stringify({
        client_id: document.getElementById('cred-client-id').value,
        username: document.getElementById('cred-username').value,
        password: document.getElementById('cred-password').value,
      }),
    });
    const data = await res.json();
    if (!res.ok) { status.textContent = `Failed: HTTP ${res.status} — ${data.detail || 'error'}`; return; }
    status.textContent = `Saved credentials for client "${data.client_id}" on ${data.capability_id} — works whether it's draft or approved. Try it via the chatbot above (§0), or approve it first in §2 below.`;
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
  populateCapabilityDropdowns();
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
loadSystems();
refreshAll();
</script>
</body>
</html>
"""
