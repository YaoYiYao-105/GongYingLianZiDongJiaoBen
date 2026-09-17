"""Crash-safe progress journal.

Appends one JSON object per processed order so that an interrupted run can be
resumed without re-submitting work that already succeeded.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .paths import ensure_dirs, state_dir


def _journal_path(day: date | None = None) -> Path:
    ensure_dirs()
    return state_dir() / f"{day or date.today():%Y-%m-%d}.jsonl"


def load_completed(day: date | None = None) -> set[str]:
    """Order numbers that already finished successfully today."""
    path = _journal_path(day)
    if not path.exists():
        return set()
    completed: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("status") == "succeeded":
            completed.add(record.get("order_no", ""))
    return completed


def append(record: dict, day: date | None = None) -> None:
    with _journal_path(day).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
