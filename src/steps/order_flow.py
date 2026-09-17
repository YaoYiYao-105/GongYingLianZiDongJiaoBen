"""Step 2 — navigate from an order number to its box-code maintenance page."""

from __future__ import annotations

from ..config import resolve


def open_order_detail(page, order_no: str, selectors: dict, timeout_ms: int) -> None:
    """Click the dispatched-order entry that carries this order number."""
    entry = page.get_by_text(order_no, exact=True).first
    if not entry.count():
        raise RuntimeError(f"order entry {order_no} not present on the query result page")
    entry.click()
    page.wait_for_load_state("networkidle", timeout=timeout_ms)


def open_approval_form(page, selectors: dict, timeout_ms: int) -> None:
    link = resolve(page, selectors["approval_link"], timeout_ms)
    if link is None:
        raise RuntimeError("approval form link not found — tighten steps.order_flow.approval_link")
    link.click()
    page.wait_for_load_state("networkidle", timeout=timeout_ms)
