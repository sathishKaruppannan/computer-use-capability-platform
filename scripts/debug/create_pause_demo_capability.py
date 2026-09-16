"""Saves a SEPARATE capability, lookup-member-savings-balance-pause-demo.v1, identical to
the real lookup-member-savings-balance.v1 except its search step (steps[1]) carries an
injected pause ErrorRule watching for the demo app's "Session Notice" interstitial (member
10003 always shows it -- demo_app/app.py). This exists purely to drive the human-handoff
intervention flow for real, through the actual running platform API and a visible browser,
instead of only inside tests/test_intervention.py.

Artifact construction lives in capabilities/demo_seed.py (build_pause_demo), shared with
POST /admin/seed-demo-capabilities -- the one-click UI equivalent of running this script.

Saved as a distinct id -- untracked local file, doesn't touch the real approved artifact.

Run once (`uv run python scripts/debug/create_pause_demo_capability.py`), then see
docs/REST_API_TEST_SCENARIOS.md's human handoff section for the full curl walkthrough this
backs: execute against memberId 10003, watch it pause, GET /interventions, view the
screenshot, resolve the dialog in the visible browser yourself, POST .../resume.
"""

from pathlib import Path

from capability_platform.capabilities.demo_seed import build_pause_demo
from capability_platform.capabilities.store import ArtifactStore


def main() -> None:
    store = ArtifactStore(Path("artifacts"))
    demo = build_pause_demo(store)
    path = store.save(demo)
    print(f"Saved {demo.qualified_id} to {path}")


if __name__ == "__main__":
    main()
