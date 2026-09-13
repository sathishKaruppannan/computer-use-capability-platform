# Evidence

Run `scripts/capture_evidence.sh` after adding `ANTHROPIC_API_KEY` to `.env`.
It creates a real Claude discovery trace, the emitted artifact, deterministic replay traces,
a business-outcome replay, and screenshots on failure under `evidence/runs/`.

Do not commit credentials, cookies, or real customer data. The demo identifiers are synthetic.

