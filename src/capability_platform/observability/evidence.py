import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar


class Redactor:
    patterns: ClassVar[list[tuple[re.Pattern[str], str]]] = [
        (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
        (re.compile(r"(?i)(authorization[\"':= ]+)([^\s,\"}]+)"), r"\1[REDACTED_TOKEN]"),
        (re.compile(r"(?i)(api[_-]?key[\"':= ]+)([^\s,\"}]+)"), r"\1[REDACTED_SECRET]"),
        (re.compile(r"(?i)(cookie[\"':= ]+)([^\s,\"}]+)"), r"\1[REDACTED_COOKIE]"),
        (re.compile(r"(?i)(session[_-]?id[\"':= ]+)([^\s,\"}]+)"), r"\1[REDACTED_SESSION]"),
    ]

    @classmethod
    def clean(cls, value: Any) -> Any:
        encoded = json.dumps(value, default=str)
        for pattern, replacement in cls.patterns:
            encoded = pattern.sub(replacement, encoded)
        return json.loads(encoded)


class EvidenceCollector:
    def __init__(self, root: Path, run_id: str) -> None:
        self.run_dir = root / "runs" / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.run_dir / "events.jsonl"

    def event(self, event_type: str, **data: Any) -> None:
        record = Redactor.clean(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": event_type,
                **data,
            }
        )
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")

    async def screenshot(self, image_bytes: bytes, name: str) -> str:
        """Takes raw image bytes, not a driver object — callers get bytes from their own
        surface/adapter (e.g. `await surface.screenshot()`), keeping this evidence sink
        independent of any particular automation driver."""
        path = self.run_dir / f"{name}.png"
        path.write_bytes(image_bytes)
        return str(path)
