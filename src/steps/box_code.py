"""Step 3 — the repetitive core: write box code 1 into every product row."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..config import resolve, resolve_all

BOX_CODE_VALUE = "1"


@dataclass
class RowStats:
    filled: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.filled + self.skipped + self.failed


def _row_input(row, candidates: list[str], timeout_ms: int):
    return resolve(row, candidates, timeout_ms)


def fill_rows(
    page,
    selectors: dict,
    *,
    commit: bool,
    log: Callable[[str], None],
    pause: Callable[[], None],
    timeout_ms: int = 5000,
) -> RowStats:
    """Walk the box-code table and set every row's box code to 1.

    ``commit=False`` performs a dry run: rows are inspected but nothing is
    typed, so the operator can confirm the target list before any write happens.
    """
    stats = RowStats()

    rows = resolve_all(page, selectors["rows"], timeout_ms)
    if rows is None:
        raise RuntimeError("box-code table not found — tighten steps.box_code.rows")

    row_count = rows.count()
    log(f"box-code table contains {row_count} row(s)")

    for index in range(row_count):
        row = rows.nth(index)
        try:
            box_input = _row_input(row, selectors["box_input"], timeout_ms)
            if box_input is None:
                stats.failed += 1
                log(f"row {index + 1}: box-code input not found")
                continue

            if (box_input.input_value() or "").strip() == BOX_CODE_VALUE:
                stats.skipped += 1
                log(f"row {index + 1}: already 1, skipped")
                continue

            if not commit:
                stats.filled += 1
                log(f"row {index + 1}: would set box code to 1")
                pause()
                continue

            date_cell = resolve(row, selectors["date_cell"], timeout_ms)
            if date_cell is not None:
                date_cell.click()
                pause()

            box_input.fill(BOX_CODE_VALUE)
            stats.filled += 1
            log(f"row {index + 1}: box code set to 1")
            pause()
        except Exception as exc:
            stats.failed += 1
            log(f"row {index + 1}: failed — {exc}")

    if commit and stats.failed == 0:
        save_button = resolve(page, selectors["save_button"], timeout_ms)
        if save_button is not None:
            save_button.click()
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            log("saved")
        else:
            log("no save button found — the table is assumed to save inline")

    return stats
