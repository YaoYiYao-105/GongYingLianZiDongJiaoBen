"""Step 1 — set the date, run the search, collect the dispatched order numbers."""

from __future__ import annotations

import re

from ..config import resolve

ORDER_NUMBER_PATTERN = re.compile(r"^\d{6,}$")


def set_today(page, selectors: dict, timeout_ms: int) -> None:
    field = resolve(page, selectors["date_input"], timeout_ms)
    if field is None:
        raise RuntimeError("date input not found — tighten steps.upi_query.date_input")
    field.click()
    page.keyboard.press("Control+A")
    page.keyboard.type(_today())
    page.keyboard.press("Enter")


def _today() -> str:
    from datetime import date

    return f"{date.today():%Y-%m-%d}"


def run_query(page, selectors: dict, timeout_ms: int) -> None:
    button = resolve(page, selectors["query_button"], timeout_ms)
    if button is None:
        raise RuntimeError("query button not found — tighten steps.upi_query.query_button")
    button.click()
    page.wait_for_load_state("networkidle", timeout=timeout_ms)


def collect_order_numbers(page, selectors: dict, timeout_ms: int) -> list[str]:
    """Read the order numbers linked from the 'dispatched orders' column."""
    locator = resolve(page, selectors["order_links"], timeout_ms)
    if locator is None:
        return []

    found: list[str] = []
    for index in range(locator.count()):
        text = (locator.nth(index).inner_text() or "").strip()
        candidate = text.split()[0] if text else ""
        if ORDER_NUMBER_PATTERN.match(candidate) and candidate not in found:
            found.append(candidate)
    return found
