#!/usr/bin/env python3
"""Fail if any committed evidence file contains an unredacted secret, API key, authorization
header, cookie, or SSN. Run before every submission: `uv run python scripts/validate_evidence.py`.

Scans text files only (json/jsonl/md/txt) — screenshots are binary and are not scanned for text
patterns (a known, documented limitation of the redaction model; see TASKS.md T7).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("raw Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("raw OpenAI-style API key", re.compile(r"sk-[A-Za-z0-9]{32,}")),
    ("unredacted SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    (
        # Requires an actual structural delimiter (quote/colon/equals), not a bare space, so
        # prose like "authorization headers" doesn't false-positive — only "authorization: ...",
        # "authorization=...", or "authorization"... shapes do.
        "unredacted authorization header value",
        re.compile(r'(?i)authorization["\':=]+\s*(?!\[REDACTED_TOKEN\])\S'),
    ),
    (
        "unredacted api key field value",
        re.compile(r'(?i)api[_-]?key["\':=]+\s*(?!\[REDACTED_SECRET\])\S'),
    ),
    ("bearer token", re.compile(r"Bearer [A-Za-z0-9._-]{10,}")),
    ("cookie header/assignment", re.compile(r'(?i)\b(set-)?cookie["\':\s]*[:=]\s*\S')),
    ("session id assignment", re.compile(r'(?i)session[_-]?id["\':=]+\s*\S')),
]

TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".txt"}


def scan(root: Path) -> list[str]:
    problems = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in FORBIDDEN_PATTERNS:
            for match in pattern.finditer(text):
                problems.append(f"{path}: {label} -> {match.group(0)[:40]!r}")
    return problems


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("evidence")
    scanned = [p for p in root.rglob("*") if p.is_file() and p.suffix in TEXT_SUFFIXES]
    problems = scan(root)
    if problems:
        print(f"REDACTION CHECK FAILED — {len(problems)} issue(s) across {len(scanned)} files:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"Redaction check passed: {len(scanned)} text files scanned under {root}, 0 issues.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
