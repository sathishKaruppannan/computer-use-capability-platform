---
name: review-artifact
description: Review a computer-use artifact for determinism, safety, and portability.
---

# Review an artifact

Validate the selected JSON with `CapabilityArtifact`, then review:

1. Inputs and outputs are typed and documented.
2. Runtime values are parameterized; secrets and raw PII are absent.
3. Every interactive step has a robust primary target and justified fallbacks.
4. Risk classifications match the action, and risky actions require approval.
5. Known business outcomes are not represented as system failures.
6. Recoveries are bounded; unknown states pause safely.
7. Steps and the final flow have verifiable checkpoints.
8. Vendor/version binding and tenant overrides fail closed.

Return findings by severity with precise artifact step IDs. Do not modify the artifact unless asked.

