"""Run artifacts: per-run folders, screenshots and the summary table."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .paths import ensure_dirs, runs_dir


@dataclass
class OrderResult:
    order_no: str
    status: str = "pending"  # pending | succeeded | skipped | failed
    rows_filled: int = 0
    rows_skipped: int = 0
    rows_failed: int = 0
    error: str = ""


@dataclass
class RunReport:
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    finished_at: str = ""
    dry_run: bool = True
    orders: list[OrderResult] = field(default_factory=list)

    def totals(self) -> dict[str, int]:
        return {
            "orders": len(self.orders),
            "succeeded": sum(o.status == "succeeded" for o in self.orders),
            "skipped": sum(o.status == "skipped" for o in self.orders),
            "failed": sum(o.status == "failed" for o in self.orders),
            "rows_filled": sum(o.rows_filled for o in self.orders),
        }


class RunContext:
    """Owns the artifact directory for a single invocation."""

    def __init__(self, sink: Callable[[str], None] | None = None) -> None:
        ensure_dirs()
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.directory: Path = runs_dir() / stamp
        self.directory.mkdir(parents=True, exist_ok=True)
        self.log_path = self.directory / "run.log"
        self._sink = sink

    def log(self, message: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        print(line, flush=True)
        if self._sink is not None:
            self._sink(line)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def screenshot(self, page, label: str) -> Path | None:
        """Capture the page. These images contain live data, never commit them."""
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label)
        path = self.directory / f"{safe}.png"
        try:
            page.screenshot(path=str(path), full_page=True)
            return path
        except Exception as exc:
            self.log(f"screenshot failed for {label}: {exc}")
            return None

    def dump_html(self, page, label: str) -> Path | None:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label)
        path = self.directory / f"{safe}.html"
        try:
            path.write_text(page.content(), encoding="utf-8")
            return path
        except Exception as exc:
            self.log(f"html dump failed for {label}: {exc}")
            return None

    def save(self, report: RunReport) -> Path:
        report.finished_at = datetime.now().isoformat(timespec="seconds")
        path = self.directory / "report.json"
        payload = asdict(report)
        payload["totals"] = report.totals()
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
