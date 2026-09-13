---
name: run-demo
description: Validate and demonstrate Claude discovery followed by deterministic replay.
---

# Run the end-to-end demo

1. Confirm `.env` exists and contains `ANTHROPIC_API_KEY`; never print its value.
2. Run `uv run pytest -q -m "not e2e"`.
3. Start `demo_app.app:app` on port 8001 if it is not already healthy.
4. Run discovery for member 10001.
5. Inspect the emitted artifact for parameterization and sensitive values.
6. Replay for 10002 and require `savingsBalance == 1220.0`.
7. Replay for 99999 and require `MEMBER_NOT_FOUND`.
8. Report artifact and evidence paths plus any failures. Stop the server you started.

Never claim the discovery trace is real unless Claude was actually called successfully.

