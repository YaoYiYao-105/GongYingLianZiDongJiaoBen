"""End-to-end test driving the real workflow with a real browser.

tests/test_workflow.py substitutes a state machine for the browser; this test
does the opposite and keeps everything real. Playwright launches an actual
Chromium, the workflow navigates real pages served by tests/mock_portal.py over
HTTP, and the assertions are made against what the server actually received.

It is the closest thing to the production run that can happen without access to
the supplier's login. If no Playwright browser is installed the test skips
rather than failing, so the suite still runs on a bare machine.
"""

from __future__ import annotations

import json
import time

import pytest

from src import browser as browser_module
from src import config as config_module
from src import report as report_module
from src import state as state_module
from src import workflow
from demo.mock_portal import serve

ORDERS = ["260917001", "260917002"]
ROWS_PER_ORDER = 4


def _browser_available() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
        return True, ""
    except Exception as exc:  # not installed, or cannot launch here
        return False, str(exc)


def _write_config(directory, base_url: str) -> None:
    config = {
        "version": 1,
        "base_url": f"{base_url}/upiMaintain",
        "behavior": {"minimize_window": False},
        "timing": {"action_delay_ms": 20, "action_jitter_ms": 20, "nav_timeout_ms": 15000},
        "steps": {
            "upi_query": {
                "date_input": ["placeholder=请选择日期"],
                "query_button": ["role=button[name='查询']"],
                "order_links": ["css=#results a"],
            },
            "order_flow": {
                "approval_link": ["role=link[name='订货审批单']"],
            },
            "box_code": {
                "rows": ["css=table tbody tr"],
                "date_cell": ["css=td:nth-child(1)"],
                "box_input": ["css=input"],
                "save_button": ["role=button[name='保存']"],
            },
        },
    }
    (directory / "selectors.json").write_text(
        json.dumps(config, ensure_ascii=False), encoding="utf-8"
    )


def _wait(predicate, timeout: float = 8.0) -> bool:
    """Wait for a server-side effect, which lands asynchronously."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def live_portal(tmp_path, monkeypatch):
    available, reason = _browser_available()
    if not available:
        pytest.skip(f"no usable Playwright browser: {reason}")

    monkeypatch.setattr(config_module, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(browser_module, "browser_profile_dir", lambda: tmp_path / "profile")
    monkeypatch.setattr(browser_module, "ensure_dirs", lambda: None)
    monkeypatch.setattr(report_module, "runs_dir", lambda: tmp_path / "runs")
    monkeypatch.setattr(report_module, "ensure_dirs", lambda: None)
    monkeypatch.setattr(state_module, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(state_module, "ensure_dirs", lambda: None)

    with serve(orders=ORDERS, rows=ROWS_PER_ORDER) as (state, base_url):
        _write_config(tmp_path, base_url)
        yield state


def test_commit_walks_the_real_pages_and_saves_every_row(live_portal):
    report = workflow.run(commit=True)

    assert [order.status for order in report.orders] == ["succeeded", "succeeded"]
    assert _wait(lambda: len(live_portal.saved) == len(ORDERS)), "orders were not submitted"

    for order in ORDERS:
        assert live_portal.rows[order] == ["1"] * ROWS_PER_ORDER
    assert [entry["order"] for entry in live_portal.saved] == ORDERS


def test_dry_run_navigates_but_never_writes(live_portal):
    report = workflow.run(commit=False)

    assert report.dry_run is True
    assert [order.status for order in report.orders] == ["succeeded", "succeeded"]
    assert [order.rows_filled for order in report.orders] == [ROWS_PER_ORDER] * len(ORDERS)

    time.sleep(0.5)
    assert live_portal.saved == [], "a dry run submitted data"
    assert all(
        value == "" for values in live_portal.rows.values() for value in values
    ), "a dry run typed into the table"


def test_second_run_skips_orders_already_completed(live_portal):
    workflow.run(commit=True)
    first_pass = len(live_portal.saved)

    second = workflow.run(commit=True)

    assert [order.status for order in second.orders] == ["skipped", "skipped"]
    time.sleep(0.5)
    assert len(live_portal.saved) == first_pass, "a completed order was submitted twice"
