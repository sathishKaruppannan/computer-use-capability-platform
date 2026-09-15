from __future__ import annotations

from pathlib import Path
from typing import Protocol

from capability_platform.access.models import InquiryRecord


class InquiryTracker(Protocol):
    def record(self, record: InquiryRecord) -> Path: ...
    def get(self, inquiry_id: str) -> InquiryRecord | None: ...


class JSONInquiryTracker:
    """One JSON file per inquiry_id under `root` — same per-entity-file pattern as
    ArtifactStore/JSONCredentialStore, so this is a client-inspectable, swappable-for-a-real-DB
    audit trail of every discover/execute request, keyed by our internal inquiry_id and carrying
    the client's own correlation id (client_inquiry_id) for their side of the tracking."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def record(self, record: InquiryRecord) -> Path:
        path = self.root / f"{record.inquiry_id}.json"
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        return path

    def get(self, inquiry_id: str) -> InquiryRecord | None:
        path = self.root / f"{inquiry_id}.json"
        if not path.exists():
            return None
        return InquiryRecord.model_validate_json(path.read_text(encoding="utf-8"))
