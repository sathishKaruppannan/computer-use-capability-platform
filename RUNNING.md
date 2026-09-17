# Running this project (quick start for reviewers)

Terse, operational companion to `README.md` (architecture/design narrative) and `REPORT.md`
(design rationale). Start here if you just want it running and want to know what's available to
poke at — `evidence/README.md` and `docs/REST_API_TEST_SCENARIOS.md` go deeper on specific flows.

## 1. Install

**Option A — `uv` (what this repo was built and tested with, recommended):**

```bash
uv sync --extra dev
uv run playwright install chromium
```

**Option B — plain `pip`, no `uv` required:**

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

`requirements.txt` pins the exact versions this codebase's test suite was last verified
against. Prefer Option A if available — `uv.lock` is the real source of truth; `requirements.txt`
is a convenience export of it, generated for reviewers without `uv` installed. Either way, from
here on every command below is shown as `uv run ...` — with Option B, drop the `uv run` prefix
(the venv is already active).

## 2. Configure

```bash
cp .env.example .env
```

Only `ANTHROPIC_API_KEY` is required, and only for running *discovery* (`discover`,
`POST /v1/discover` on a cache miss). Everything else — deterministic replay, the REST API, the
demo app, MCP exposure, and the entire non-`e2e` test suite — works with no key at all, since
replay never instantiates an LLM client (enforced by
`tests/test_replay_e2e.py::test_replay_never_instantiates_llm_client`). `OPENAI_API_KEY` is
optional (a per-call discovery fallback only, never a default — see README "OpenAI as a discovery
fallback").

## 3. Run both apps

Two terminals — start the demo app first, since discovery/replay drives it:

```bash
# Terminal 1 — the legacy-style web app being automated, port 8001
uv run uvicorn demo_app.app:app --port 8001
# equivalent: make demo

# Terminal 2 — the platform's REST API (discover/execute/MCP-backing), port 8000
uv run uvicorn capability_platform.api.app:app --port 8000
# equivalent: make platform
```

Then:

- `http://127.0.0.1:8000/docs` — live OpenAPI/Swagger UI for every REST route (every
  request/response field is annotated with its purpose — see `api/schemas/{requests,responses}.py`
  and the `ExecutionResult`/`RunError` models).
- `http://127.0.0.1:8000/admin` — a one-page dashboard that drives discover → review → approve →
  execute end-to-end, including the pause/approval intervention demos, without curl.
- `http://127.0.0.1:8001` — the demo app itself, if you want to see what's actually being
  automated.

An artifact for the primary scenario (`lookup-member-savings-balance.v1`) already ships in
`artifacts/`, so you can run replay/execute immediately without running discovery first — see
README "Exact demo path" for the full `make demo` → `make discover` → `make replay` walkthrough,
and REPORT.md §3 for what a `success` / `business_outcome` / `paused` / `failure` result each
mean.

## 4. Run the tests

```bash
uv run pytest -q -m "not e2e"     # fast — no browser, no running demo app, no API keys needed
uv run pytest -q -m e2e           # needs the demo app running on :8001 (Playwright, real browser)
uv run ruff check .               # lint
uv run python scripts/validate_evidence.py   # fails if any evidence/ file has an unredacted secret/PII
```

`-m "not e2e"` is what CI/a quick sanity check should run; it's fully self-contained. The `e2e`
marker is reserved for tests that drive a real Playwright browser against the demo app.

## 5. Debug flow scripts

`scripts/debug/*.py` are standalone, single-steppable harnesses (each has good breakpoints
documented in its own docstring) for flows that are otherwise only exercised inside pytest or a
multi-step curl session:

- `discover_v1_flow.py` — the authenticated `/v1/discover` resolver: reuse-check →
  Claude-discovery-on-miss → draft → approve → execute → reuse on a repeat call. Runs the real
  FastAPI app in-process against a throwaway temp directory, so it's safe to re-run and never
  touches `artifacts/`, `data/credentials/`, or `evidence/` under the repo root.
- `create_pause_demo_capability.py` — seeds a capability that deliberately triggers the
  same-session human-handoff pause flow against a real running platform + browser.
- `create_approval_demo_capability.py` — seeds a capability with a step above the configured risk
  threshold, to drive the risky-action approval gate (`POST /interventions/{id}/resume`) for
  real.
- `mcp_tool_invocation.py` — calls the generated MCP tool function directly, bypassing the
  stdio/JSON-RPC transport, for single-stepping in a normal debugger. Needs an approved
  capability on disk and the demo app running on :8001.

`.vscode/launch.json` already wires these up as named "Debug: ..." run configurations if you're
in VS Code.

## Everything else

- `README.md` — architecture, the full demo path, REST/MCP walkthroughs with real captured
  request/response examples.
- `REPORT.md` — design rationale: artifact schema, determinism/error handling, multi-tenant
  model, escalation/handoff, safety, and what was deliberately cut.
- `docs/ARCHITECTURE_WALKTHROUGH.md` — the architecture diagram walked box by box, each one
  mapped to its `CLAUDE.md` rule and its actual implementation (file/function).
- `docs/REST_API_TEST_SCENARIOS.md` — full curl request/response reference, including
  auth/authz/not-found failure modes; nearly every response in it is real captured output.
- `REQUIREMENTS_TRACEABILITY.md` — the take-home PDF's requirements mapped against what's
  actually implemented, with status per item.
