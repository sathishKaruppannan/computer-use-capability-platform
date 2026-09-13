# Evidence

Run `scripts/capture_evidence.sh` after adding `ANTHROPIC_API_KEY` to `.env`.
It creates a real Claude discovery trace, the emitted artifact, deterministic replay traces,
a business-outcome replay, and screenshots on failure under `evidence/runs/`.

Do not commit credentials, cookies, or real customer data. The demo identifiers are synthetic.

## Committed replay evidence (Phase 3)

The following runs were captured against the live demo app (`uv run uvicorn demo_app.app:app
--port 8001`), with `HEADLESS=true`, using **no LLM** — pure deterministic replay via
`ReplayEngine`. No discovery run is included yet; that requires a real `ANTHROPIC_API_KEY` and
is deferred to a later phase.

| Run ID | Scenario | Command | Result |
|---|---|---|---|
| `8b948227-8535-4cda-95e0-8c6453c7c39f` | Success | `capability-platform replay lookup-member-savings-balance.v1 --input memberId=10002` | `status=success`, `savingsBalance=1220.0` |
| `5cacf6fc-0876-4086-b2c8-7f7bfd3415f8` | Business outcome | `capability-platform replay lookup-member-savings-balance.v1 --input memberId=99999` | `status=business_outcome`, `business_code=MEMBER_NOT_FOUND` |
| `e97ff371-56e1-4e5f-bfde-5386983d8e5e` | Input validation failure (no browser launched) | `capability-platform replay lookup-member-savings-balance.v1` (no `--input`) | `status=failure`, `error.category=validation`, `error.code=MISSING_INPUT` |
| `33549c65-2899-4885-a091-c858bfb6dd94` | Injected hard failure (broken locator) | One-off script executing the artifact with `steps[0].target` pointed at a nonexistent label | `status=failure`, `error.category=checkpoint_failed`, `error.step_id=enter-member`, screenshot at `failure-enter-member.png` |

Each run directory contains `events.jsonl` (structured, redacted log of every step) and, for
the hard-failure run, a full-page screenshot of the state at the point of failure.

## Committed discovery evidence (Phase 4)

A genuine Claude-driven discovery run against the live demo app, goal: *"Find member 10001 and
return the current savings balance."* Two real attempts were made; the first failed for a real
reason (see below, not fabricated), which was diagnosed and fixed in `agent/discovery.py`
before the second, successful attempt.

| Run ID | Result | Notes |
|---|---|---|
| `1b835d17-a5f4-4206-a7eb-8b94aaab1934` | **Real failure** — `KeyError: 'strategy'` | Claude's 4th decision (`extract`) put the observed value `"$4,250.25"` directly into the `output` field instead of providing a `strategy`/`value` locator, because neither the tool schema nor the system prompt said `output` was a field *name*, not the value. Crashed before an artifact was produced. Evidence for steps 0-3 (which succeeded) is preserved in this run's `events.jsonl`. |
| `aceafd67-b8af-46bd-826a-e914d9d4f596` | Discovery **succeeded** (schema-valid artifact produced) but the artifact was flawed | After fixing the crash (clarified prompt/schema, added a defensive check), discovery completed, but the `extract` step's locator was `strategy=text, value="$4,250.25"` — the literal balance for member 10001. This overfits to one input and cannot generalize (replay for a different member would fail to find that exact text). |
| `8dcc3190-6b05-44b5-b44b-99cb0292153e` | Discovery **succeeded** with a generalizable artifact | After adding an `xpath` locator option to the tool schema and prompting Claude to reference the stable "Primary Savings" row label instead of the volatile balance text, and after fixing `_enrich_errors` to attach the `MEMBER_NOT_FOUND` rule to every post-search step (not just the last), Claude produced `extract` step `strategy=xpath, value=//tr[td[contains(.,'Primary Savings')]]/td[2]` — a locator relative to a label that's stable across members. This is the artifact now saved at `artifacts/lookup-member-savings-balance.v1.json`. |

Requirement checks against the successful run (`8dcc3190-...`):
- **No LLM key printed/logged**: confirmed by grep — the raw key value appears nowhere in `events.jsonl`, `artifact.json`, or anywhere else in the repo outside the gitignored `.env`.
- **Real observe-decide-act loop**: 4 rounds of `discovery.observed` → `discovery.decided` → `discovery.acted`, each a real `messages.create` call (not scripted).
- **Browser observations treated as untrusted data**: the model can only choose from a fixed enum of actions via forced tool-use (`tool_choice`); nothing in the observed page text is ever executed as an instruction.
- **Checkpoint verified before completion**: `agent/discovery.py`'s `complete` branch now asserts `surface.visible(success_target)` (the "Savings Account" heading) before accepting completion — previously this was not checked at all (a real gap found and fixed in this phase).
- **No model transcript persisted as the capability**: `artifact.json` contains only typed steps/locators/checkpoints — no chat history or raw model text.
- **No credentials/PII in the artifact**: confirmed by manual inspection and grep.
- **`{{memberId}}` parameterization**: `step-1.value == "{{memberId}}"`.

**Replay of the generated artifact for member 10002 (no LLM)**, run after discovery:

| Run ID | Input | Result |
|---|---|---|
| `c5c43265-c4ce-486c-aee6-c600de73faa1` | `memberId=10002` | `status=success`, `savingsBalance=1220.0` — the discovery-generated artifact, discovered against member 10001, correctly replays for a different member with no LLM involved. |
| `ff5b2a3c-2e61-4520-b8cc-d83fbf528eef` | `memberId=99999` | `status=business_outcome`, `business_code=MEMBER_NOT_FOUND` |

## User-reported failure, diagnosed and fixed (Phase 4b)

Running the same discovery goal again (user-triggered), a fourth real run
(`4bb650a8-1609-43fe-822c-0feba1697827`) failed with `LookupError: role:Search matched 0`.
Diagnosis: Claude's decision was `{"strategy": "role", "name": "button", "value": "Search"}` —
`value`/`name` swapped for the `role` strategy, where `value` must be the ARIA role type and
`name` the accessible label. The tool schema didn't state this per-strategy rule clearly enough.
Fixed in `agent/discovery.py` (explicit rule + worked example in both the prompt and the schema
field descriptions). Re-run afterward with the same goal succeeded
(`created_at: 2026-09-13T21:50:26Z`), and replay for member 10002 against the regenerated
artifact returned `status=success, savingsBalance=1220.0` (run `226215df-...`).

**Note on two older evidence runs** (`c1dbc057-d8de-4304-9c34-36c3ff5750dd`,
`ee6e3d89-0b83-4b5a-9166-7ee4b8e83734`): these use the pre-Phase-4 artifact's step IDs
(`enter-member`, `search`, ...) and were not produced by a command run explicitly in this
session's visible history — they appear to be from an automated background pass earlier in the
session. Their content is genuine (real successful/business-outcome replays against the live
demo app), just predating the artifact regenerated in this phase. Left in place rather than
deleted, since they are real runs, not fabricated ones.

