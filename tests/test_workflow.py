"""End-to-end test of the orchestration against a fake portal.

The real portal needs an authenticated session and cannot be reached from CI,
so the four pages involved are replaced by a small state machine. Everything
else — the real step modules, selector resolution, the journal and reporting —
runs unchanged. Only the browser is substituted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import browser as browser_module
from src import report as report_module
from src import state as state_module
from src import workflow

ORDER_NUMBERS = ["260917001", "260917002"]

CONFIG = {
    "version": 1,
    "base_url": "https://portal.invalid/upiMaintain",
    "behavior": {"minimize_window": False},
    "timing": {"action_delay_ms": 0, "action_jitter_ms": 0, "nav_timeout_ms": 1000},
    "steps": {
        "upi_query": {
            "date_input": ["css=input[placeholder*='日期']"],
            "query_button": ["role=button[name='查询']"],
            "order_links": ["css=a[href*='order']"],
        },
        "order_flow": {
            "approval_link": ["role=link[name='订货审批单']", "text=订货审批单"],
        },
        "box_code": {
            "rows": ["css=.el-table__body tbody tr"],
            "date_cell": ["css=td:nth-child(2)"],
            "box_input": ["css=input"],
            "save_button": ["role=button[name='保存']"],
        },
    },
}


# --------------------------------------------------------------------- fakes
class Locator:
    def __init__(self, elements):
        self._elements = list(elements)

    @property
    def first(self):
        return Locator(self._elements[:1])

    def count(self):
        return len(self._elements)

    def nth(self, index):
        return Locator([self._elements[index]])

    def is_visible(self, timeout=None):
        return bool(self._elements)

    def inner_text(self):
        return self._elements[0].inner_text()

    def click(self):
        self._elements[0].click()

    def input_value(self):
        return self._elements[0].input_value()

    def fill(self, value):
        self._elements[0].fill(value)

    def locator(self, selector):
        return self._elements[0].locator(selector)


class Field:
    def __init__(self):
        self.value = ""
        self.clicks = 0

    def click(self):
        self.clicks += 1

    def is_visible(self, timeout=None):
        return True

    def input_value(self):
        return self.value

    def fill(self, value):
        self.value = value

    def inner_text(self):
        return self.value


class Button:
    def __init__(self, action):
        self._action = action
        self.clicks = 0

    def click(self):
        self.clicks += 1
        self._action()

    def is_visible(self, timeout=None):
        return True


class OrderLink:
    def __init__(self, portal, order_no):
        self._portal = portal
        self._order = order_no

    def inner_text(self):
        return self._order

    def click(self):
        self._portal.open_order(self._order)

    def is_visible(self, timeout=None):
        return True


class DateCell:
    def __init__(self, portal):
        self._portal = portal

    def click(self):
        self._portal.date_clicks += 1

    def is_visible(self, timeout=None):
        return True

    def inner_text(self):
        return "2026-09-17"


class BoxInput:
    def __init__(self, portal, order_no, index):
        self._portal = portal
        self._order = order_no
        self._index = index

    def input_value(self):
        return self._portal.rows[self._order][self._index]

    def fill(self, value):
        self._portal.rows[self._order][self._index] = value
        self._portal.fill_calls.append((self._order, self._index, value))

    def is_visible(self, timeout=None):
        return True


class Row:
    def __init__(self, portal, order_no, index):
        self._portal = portal
        self._order = order_no
        self._index = index

    def locator(self, selector):
        if "input" in selector:
            if self._index in self._portal.missing_inputs:
                return Locator([])
            return Locator([BoxInput(self._portal, self._order, self._index)])
        return Locator([DateCell(self._portal)])


class Keyboard:
    def __init__(self):
        self.pressed: list[str] = []
        self.typed: list[str] = []

    def press(self, key):
        self.pressed.append(key)

    def type(self, text):
        self.typed.append(text)


class Page:
    def __init__(self, portal):
        self.portal = portal
        self.keyboard = Keyboard()
        self.url = CONFIG["base_url"]

    def goto(self, url, **kwargs):
        self.url = url
        # Returning to the list URL shows a blank form, not the old results.
        self.portal.state = "query"
        self.portal.current = None

    def wait_for_load_state(self, *args, **kwargs):
        return None

    def screenshot(self, path=None, full_page=False):
        Path(path).write_bytes(b"fake-screenshot")

    def locator(self, selector):
        return self.portal.locator(selector)

    def get_by_role(self, role, **kwargs):
        return self.portal.by_role(role, kwargs)

    def get_by_text(self, text, exact=False):
        return self.portal.by_text(text)

    def get_by_placeholder(self, text):
        return Locator([])

    def get_by_label(self, text):
        return Locator([])


class Portal:
    """A state machine standing in for the portal's four pages."""

    def __init__(self, orders, row_count=3, prefilled=0, missing_inputs=()):
        self.orders = list(orders)
        self.row_count = row_count
        self.missing_inputs = set(missing_inputs)
        self.rows = {
            order: ["1" if index < prefilled else "" for index in range(row_count)]
            for order in self.orders
        }
        self.state = "query"
        self.current = None
        self.fill_calls: list[tuple] = []
        self.date_clicks = 0
        self.saved: list[str] = []
        self.date_field = Field()
        self.query_button = Button(self._search)
        self.save_button = Button(self._save)

    # --- transitions
    def _search(self):
        self.state = "results"

    def open_order(self, order_no):
        if self.state != "results":
            raise AssertionError("an order link was clicked while the list was not on screen")
        self.current = order_no
        self.state = "detail"

    def open_approval(self):
        self.state = "box"

    def _save(self):
        self.saved.append(self.current)

    # --- element lookups
    def locator(self, selector):
        if "placeholder" in selector or "date-editor" in selector:
            return Locator([self.date_field] if self.state == "query" else [])
        if "tr" in selector:
            if self.state != "box":
                return Locator([])
            return Locator([Row(self, self.current, i) for i in range(self.row_count)])
        if "href" in selector:
            if self.state != "results":
                return Locator([])
            return Locator([OrderLink(self, order) for order in self.orders])
        return Locator([])

    def by_role(self, role, kwargs):
        name = kwargs.get("name", "")
        if role == "button" and name == "查询" and self.state in ("query", "results"):
            return Locator([self.query_button])
        if role == "button" and name == "保存" and self.state == "box":
            return Locator([self.save_button])
        if role == "link" and name == "订货审批单" and self.state == "detail":
            return Locator([Button(self.open_approval)])
        return Locator([])

    def by_text(self, text):
        if self.state == "results" and text in self.orders:
            return Locator([OrderLink(self, text)])
        if self.state == "detail" and text == "订货审批单":
            return Locator([Button(self.open_approval)])
        return Locator([])


class Session:
    def __init__(self, page):
        self.page = page

    def close(self):
        return None


@pytest.fixture
def portal_factory(tmp_path, monkeypatch):
    def build(**kwargs):
        portal = Portal(**kwargs)
        session = Session(Page(portal))

        monkeypatch.setattr(report_module, "runs_dir", lambda: tmp_path / "runs")
        monkeypatch.setattr(report_module, "ensure_dirs", lambda: None)
        monkeypatch.setattr(state_module, "state_dir", lambda: tmp_path)
        monkeypatch.setattr(state_module, "ensure_dirs", lambda: None)
        monkeypatch.setattr(browser_module, "launch", lambda **kw: session)
        monkeypatch.setattr(browser_module, "minimize", lambda session: False)
        monkeypatch.setattr(browser_module, "restore", lambda session: False)
        monkeypatch.setattr(browser_module, "looks_logged_out", lambda url, page: False)
        monkeypatch.setattr(workflow, "load_config", lambda: CONFIG)
        return portal

    return build


# --------------------------------------------------------------------- tests
def test_dry_run_lists_the_work_without_writing_anything(portal_factory):
    portal = portal_factory(orders=ORDER_NUMBERS, row_count=3)

    report = workflow.run(commit=False)

    assert report.dry_run is True
    assert [order.status for order in report.orders] == ["succeeded", "succeeded"]
    assert [order.rows_filled for order in report.orders] == [3, 3]
    assert portal.fill_calls == [], "a dry run must not type into the table"
    assert portal.saved == [], "a dry run must not submit"


def test_commit_sets_every_row_to_one(portal_factory):
    portal = portal_factory(orders=ORDER_NUMBERS, row_count=3)

    report = workflow.run(commit=True)

    assert report.totals()["rows_filled"] == 6
    assert all(value == "1" for values in portal.rows.values() for value in values)
    assert portal.saved == ORDER_NUMBERS, "each order is submitted once"
    assert portal.date_clicks == 6, "the order date is clicked before typing"


def test_a_second_run_skips_orders_that_already_succeeded(portal_factory):
    portal = portal_factory(orders=ORDER_NUMBERS, row_count=2)
    workflow.run(commit=True)
    portal.fill_calls.clear()

    second = workflow.run(commit=True)

    assert [order.status for order in second.orders] == ["skipped", "skipped"]
    assert portal.fill_calls == [], "completed orders must not be touched again"


def test_rows_already_holding_one_are_left_alone(portal_factory):
    portal = portal_factory(orders=["260917001"], row_count=3, prefilled=3)

    report = workflow.run(commit=True)

    assert report.orders[0].rows_skipped == 3
    assert portal.fill_calls == []


def test_a_failed_row_is_reported_and_the_table_is_not_submitted(portal_factory):
    portal = portal_factory(orders=["260917001"], row_count=3, missing_inputs={1})

    report = workflow.run(commit=True)

    result = report.orders[0]
    assert result.status == "failed"
    assert (result.rows_filled, result.rows_failed) == (2, 1)
    assert portal.saved == [], "a partially failed table must never be submitted"


def test_all_orders_are_collected_not_just_the_first(portal_factory):
    portal_factory(orders=["260917001", "260917002", "260917003"], row_count=1)

    report = workflow.run(commit=False)

    assert len(report.orders) == 3, "only the first order link was collected"


def test_limit_processes_only_the_requested_number_of_orders(portal_factory):
    portal_factory(orders=["260917001", "260917002", "260917003"], row_count=1)

    report = workflow.run(commit=False, limit=2)

    assert [order.order_no for order in report.orders] == ["260917001", "260917002"]


# ------------------------------------------------------- abort handling
def _saved_report(tmp_path) -> dict:
    files = sorted((tmp_path / "runs").glob("*/report.json"))
    assert files, "no report.json was written"
    return json.loads(files[-1].read_text(encoding="utf-8"))


def _broken_config() -> dict:
    broken = json.loads(json.dumps(CONFIG))
    broken["steps"]["upi_query"]["query_button"] = ["role=button[name='不存在的按钮']"]
    return broken


def test_not_logged_in_is_reported_as_an_abort(portal_factory, monkeypatch, tmp_path):
    portal_factory(orders=ORDER_NUMBERS, row_count=2)
    monkeypatch.setattr(browser_module, "looks_logged_out", lambda url, page: True)

    report = workflow.run(commit=False)

    assert report.aborted is True
    assert report.abort_code == 2
    assert report.exit_code() == 2
    assert "未登录" in report.abort_reason
    assert report.orders == []
    assert _saved_report(tmp_path)["aborted"] is True


def test_a_broken_selector_aborts_instead_of_raising(portal_factory, monkeypatch, tmp_path):
    portal_factory(orders=["260917001"], row_count=1)
    monkeypatch.setattr(workflow, "load_config", _broken_config)

    report = workflow.run(commit=False)

    assert report.aborted is True
    assert report.exit_code() == 1
    assert "改版" in report.abort_reason
    assert _saved_report(tmp_path)["abort_reason"] == report.abort_reason


def test_a_missing_browser_is_reported_as_an_abort(portal_factory, monkeypatch):
    portal_factory(orders=["260917001"], row_count=1)

    def no_browser(**kwargs):
        raise RuntimeError("no usable browser found:\n  msedge: not installed")

    monkeypatch.setattr(browser_module, "launch", no_browser)

    report = workflow.run(commit=False)

    assert report.aborted is True
    assert "Edge" in report.abort_reason


def test_a_keyboard_interrupt_is_reported_as_an_abort(portal_factory, monkeypatch):
    portal_factory(orders=["260917001"], row_count=1)

    def interrupted(**kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(browser_module, "launch", interrupted)

    report = workflow.run(commit=False)

    assert report.aborted is True
    assert report.abort_code == 130
    assert "中断" in report.abort_reason


def test_the_traceback_is_kept_in_the_log_file(portal_factory, monkeypatch, tmp_path):
    """The operator sees one sentence; the detail must still be recoverable."""
    portal_factory(orders=["260917001"], row_count=1)
    monkeypatch.setattr(workflow, "load_config", _broken_config)

    workflow.run(commit=False)

    logs = sorted((tmp_path / "runs").glob("*/run.log"))
    assert logs, "no run.log was written"
    content = logs[-1].read_text(encoding="utf-8")
    assert "Traceback" in content
    assert "query button not found" in content
