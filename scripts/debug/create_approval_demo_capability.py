"""Saves a SEPARATE capability, lookup-member-savings-balance-approval-demo.v1, identical to
the real lookup-member-savings-balance.v1 except one step (steps[2], "Open Accounts") is marked
risk=RISKY -- above config/policy.json's maxRiskWithoutApproval ("reversible") -- so
PolicyEngine pauses for a real human APPROVE/DENY decision before running it. This is a
different intervention shape than the pause-demo capability
(create_pause_demo_capability.py): here `approved` is a genuine decision passed to
POST /interventions/{id}/resume, not just a dismiss-and-continue.

Artifact construction lives in capabilities/demo_seed.py (build_approval_demo), shared with
POST /admin/seed-demo-capabilities -- the one-click UI equivalent of running this script.

Exists purely to drive the risky-action approval flow for real, through the actual running
platform API, instead of only inside tests/test_approval.py.

Saved as a distinct id -- untracked local file, doesn't touch the real approved artifact.
"""

from pathlib import Path

from capability_platform.capabilities.demo_seed import build_approval_demo
from capability_platform.capabilities.store import ArtifactStore


def main() -> None:
    store = ArtifactStore(Path("artifacts"))
    demo = build_approval_demo(store)
    path = store.save(demo)
    print(f"Saved {demo.qualified_id} to {path}")


if __name__ == "__main__":
    main()
