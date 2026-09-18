"""The endpoint-driven run, exercised against a portal that behaves like the real one.

The interesting behaviour is not the happy path but the three ways this can go
quietly wrong: a save the server accepts without storing, a resumed run that
skips work, and a dry run that leaves a trace convincing enough to make the next
real run do nothing. Each of those has a test that would fail if the guard were
removed.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from src import api_workflow
from src import report as report_module
from src import state as state_module
from src.api import ApiError, Credentials

class FakeStorage:
    """Only the one method :func:`read_credentials` uses."""

    def __init__(self, values):
        self.values = values

    def evaluate(self, script, keys):
        return {key: self.values.get(key) for key in keys}


def test_a_captured_session_is_cached_in_one_pass(workspace):
    """What `main.py login` and the GUI's login button both do."""
    page = FakeStorage({"SIGN": '"S"', "login-token": '"T"', "sign-diff": '"242"'})

    api_workflow.store(api_workflow.read_credentials(page))

    assert api_workflow.load_cached() == Credentials(sign="S", token="T", skew_ms=242)

TODAY = date(2026, 9, 18)
ORDERS = ["2609180001", "2609180002"]

CONFIG = {"behavior": {"box_code": 1, "minimize_window": False}, "timing": {"nav_timeout_ms": 1000}}


def portal_row(sheet_id: str, ref: str, goods_id: int, real_qty: float, qa_days: int = 5) -> dict:
    return {
        "sheetId": sheet_id,
        "refSheetId": ref,
        "goodsId": goods_id,
        "realQty": real_qty,
        "qaDays": qa_days,
        "procDate": None,
        "overDate": None,
        "upiBoxNo": "",
    }


ROWS = {
    ORDERS[0]: [portal_row(ORDERS[0], "A", 1, 2.0), portal_row(ORDERS[0], "A", 2, 0.0)],
    ORDERS[1]: [portal_row(ORDERS[1], "B", 3, 7.0, qa_days=7)],
}


class FakePortal:
    """Stands in for :class:`src.api.PortalApi`, storing what it is handed."""

    def __init__(
        self,
        orders=None,
        rows=None,
        *,
        today=TODAY,
        drop_saves: set | None = None,
        refuse: dict | None = None,
        empty_orders: set | None = None,
    ) -> None:
        self.orders = [
            {"sheetId": number, "flag": "2"}
            for number in (ORDERS if orders is None else orders)
        ]
        self.rows = {key: [dict(row) for row in value] for key, value in (rows or ROWS).items()}
        self.today = today
        self.drop_saves = drop_saves or set()
        self.refuse = refuse or {}
        self.empty_orders = empty_orders or set()
        self.saves: list[list[dict]] = []
        self.requests: list[str] = []

    def server_today(self):
        self.requests.append("today")
        return self.today

    def pending_orders(self, **kwargs):
        self.requests.append("pending")
        return list(self.orders)

    def order_rows(self, order):
        sheet_id = str(order["sheetId"])
        self.requests.append(f"rows:{sheet_id}")
        if sheet_id in self.empty_orders:
            return []
        return [dict(row) for row in self.rows.get(sheet_id, [])]

    def save_boxes(self, entries):
        self.requests.append("save")
        if "save" in self.refuse:
            raise ApiError(self.refuse["save"], code=500000)
        self.saves.append(entries)
        for entry in entries:
            sheet_id = str(entry["sheetId"])
            if sheet_id in self.drop_saves:
                continue
            for row in self.rows.get(sheet_id, []):
                if row["goodsId"] == entry["goodsId"] and row["refSheetId"] == entry["refSheetId"]:
                    row["procDate"] = entry["procDate"] or None
                    row["overDate"] = entry["overDate"] or None
                    row["upiBoxNo"] = entry["upiBoxNo"]

    def verify_boxes(self, order):
        sheet_id = str(order["sheetId"])
        self.requests.append(f"verify:{sheet_id}")
        return [dict(row) for row in self.rows.get(sheet_id, [])]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Keep the journal, runs and the session cache inside the test directory."""
    monkeypatch.setattr(report_module, "runs_dir", lambda: tmp_path / "runs")
    monkeypatch.setattr(report_module, "ensure_dirs", lambda: None)
    monkeypatch.setattr(state_module, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(state_module, "ensure_dirs", lambda: None)
    monkeypatch.setattr(api_workflow, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(api_workflow, "load_config", lambda: CONFIG)
    return tmp_path


def written(portal) -> dict:
    """The box codes the portal ended up storing, keyed by product."""
    return {
        (row["sheetId"], row["goodsId"]): row["upiBoxNo"]
        for rows in portal.rows.values()
        for row in rows
    }


# --------------------------------------------------------------------- reading
def test_a_dry_run_reports_the_work_without_writing(workspace):
    portal = FakePortal()
    report = api_workflow.run(client=portal)

    assert report.dry_run is True
    assert [order.status for order in report.orders] == ["succeeded", "succeeded"]
    assert [order.rows_filled for order in report.orders] == [1, 1]
    assert [order.rows_skipped for order in report.orders] == [1, 0]
    assert portal.saves == []
    assert "save" not in portal.requests


def test_a_commit_writes_and_then_reads_back(workspace):
    portal = FakePortal()
    report = api_workflow.run(commit=True, client=portal)

    assert [order.status for order in report.orders] == ["succeeded", "succeeded"]
    assert [order.rows_filled for order in report.orders] == [1, 1]
    assert f"verify:{ORDERS[0]}" in portal.requests
    assert written(portal) == {
        (ORDERS[0], 1): 1,
        (ORDERS[0], 2): "",
        (ORDERS[1], 3): 1,
    }


def test_the_saved_body_matches_what_the_maintenance_page_sends(workspace):
    portal = FakePortal()
    api_workflow.run(commit=True, client=portal)

    first = portal.saves[0]
    assert first[0] == {
        "sheetId": ORDERS[0],
        "refSheetId": "A",
        "goodsId": 1,
        "realQty": 2.0,
        "procDate": "2026-09-18",
        "overDate": "2026-09-23",
        "upiBoxNo": 1,
    }
    assert first[1]["procDate"] == "" and first[1]["upiBoxNo"] == "", (
        "a row that was never allocated must be sent back empty"
    )


def test_the_box_code_comes_from_the_configuration(workspace, monkeypatch):
    monkeypatch.setattr(
        api_workflow, "load_config", lambda: {"behavior": {"box_code": 3}, "timing": {}}
    )
    portal = FakePortal()
    api_workflow.run(commit=True, client=portal)

    assert portal.saves[0][0]["upiBoxNo"] == 3
    assert written(portal)[(ORDERS[0], 1)] == 3


# ------------------------------------------------------------------ verifying
def test_a_save_the_server_accepts_but_does_not_store_is_a_failure(workspace):
    portal = FakePortal(drop_saves={ORDERS[0]})
    report = api_workflow.run(commit=True, client=portal)

    assert [order.status for order in report.orders] == ["failed", "succeeded"]
    assert report.orders[0].rows_failed == 1
    assert report.exit_code() == 1


def test_a_refused_save_fails_that_order_only(workspace):
    portal = FakePortal(refuse={"save": "订货通知单状态不为未执行，不能维护"})
    report = api_workflow.run(commit=True, client=portal)

    assert [order.status for order in report.orders] == ["failed", "failed"]
    assert "不能维护" in report.orders[0].error


def test_an_order_with_no_rows_fails_instead_of_reporting_success(workspace):
    portal = FakePortal(empty_orders={ORDERS[1]})
    report = api_workflow.run(commit=True, client=portal)

    assert [order.status for order in report.orders] == ["succeeded", "failed"]
    assert report.orders[1].error


# ------------------------------------------------------------------- resuming
def test_a_dry_run_does_not_make_the_next_commit_skip_the_work(workspace):
    """The journal records work done, and a dry run does none."""
    api_workflow.run(commit=False, client=FakePortal())

    portal = FakePortal()
    report = api_workflow.run(commit=True, client=portal)

    assert [order.status for order in report.orders] == ["succeeded", "succeeded"]
    assert portal.saves, "the dry run's journal entry suppressed the real run"


def test_a_second_commit_skips_orders_already_done_today(workspace):
    api_workflow.run(commit=True, client=FakePortal())

    portal = FakePortal()
    report = api_workflow.run(commit=True, client=portal)

    assert [order.status for order in report.orders] == ["skipped", "skipped"]
    assert portal.saves == []


def test_the_journal_is_keyed_on_the_portals_date(workspace):
    api_workflow.run(commit=True, client=FakePortal())

    assert (workspace / f"{TODAY:%Y-%m-%d}.jsonl").exists()


# ------------------------------------------------------------------ selecting
def test_a_single_order_can_be_picked_out(workspace):
    portal = FakePortal()
    report = api_workflow.run(commit=True, only_order=ORDERS[1], client=portal)

    assert [order.order_no for order in report.orders] == [ORDERS[1]]
    assert len(portal.saves) == 1


def test_the_run_can_be_capped(workspace):
    portal = FakePortal()
    report = api_workflow.run(commit=True, limit=1, client=portal)

    assert [order.order_no for order in report.orders] == [ORDERS[0]]


def test_a_day_with_nothing_pending_is_not_an_error(workspace):
    portal = FakePortal(orders=[])
    report = api_workflow.run(commit=True, client=portal)

    assert report.orders == []
    assert report.aborted is False
    assert report.exit_code() == 0


def test_orders_are_looked_for_without_a_date_filter(workspace):
    """An order notice is dated the day before it is due, so a date filter
    would silently report a day with nothing to do."""
    portal = FakePortal()
    api_workflow.run(client=portal)

    assert portal.requests[0] == "today"
    assert portal.requests[1] == "pending"


# ------------------------------------------------------------------- sessions
def test_a_cached_session_is_used_without_opening_a_browser(workspace):
    api_workflow.store(Credentials(sign="S", token="T", skew_ms=7))

    called = []
    client = FakePortal()
    api_workflow.run(
        commit=True,
        capture=lambda **kwargs: called.append(kwargs) or Credentials(sign="x", token="y"),
        client=client,
    )

    assert called == [], "the browser was opened despite a usable cached session"
    assert api_workflow.load_cached().sign == "S"


def test_a_rejected_cache_falls_back_to_the_browser(workspace, monkeypatch):
    api_workflow.store(Credentials(sign="STALE", token="T"))

    fresh = Credentials(sign="FRESH", token="T", skew_ms=1)
    calls = []

    class RejectingClient:
        def server_today(self):
            raise ApiError("expired", code=600207)

    monkeypatch.setattr(api_workflow, "PortalApi", lambda credentials, **kw: RejectingClient())

    with pytest.raises(ApiError):
        api_workflow.connect(capture=lambda **kwargs: calls.append(kwargs) or fresh, log=lambda _: None)

    assert len(calls) == 1


def test_a_valid_cache_never_reaches_the_capture(workspace, monkeypatch):
    api_workflow.store(Credentials(sign="GOOD", token="T"))
    monkeypatch.setattr(api_workflow, "PortalApi", lambda credentials, **kw: FakePortal())

    def explode(**kwargs):
        raise AssertionError("the browser should not have been opened")

    client = api_workflow.connect(capture=explode, log=lambda _: None)
    assert client is not None


def test_a_cached_session_round_trips_through_the_file(workspace):
    path = api_workflow.store(Credentials(sign="S", token="T", skew_ms=242))

    assert path.exists()
    assert api_workflow.load_cached() == Credentials(sign="S", token="T", skew_ms=242)

    api_workflow.forget()
    assert api_workflow.load_cached() is None


def test_a_corrupt_cache_is_ignored_rather_than_crashing(workspace):
    path = api_workflow.credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    assert api_workflow.load_cached() is None


def test_an_empty_cache_file_is_treated_as_signed_out(workspace):
    path = api_workflow.credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sign": "", "token": ""}), encoding="utf-8")

    assert api_workflow.load_cached() is None


# --------------------------------------------------------------------- aborts
def test_a_failure_before_the_first_order_aborts_the_run(workspace):
    class Dead:
        def server_today(self):
            raise ApiError("后台拒绝了连接")

    report = api_workflow.run(commit=True, client=Dead())

    assert report.aborted is True
    assert "后台拒绝了连接" in report.abort_reason
    assert report.exit_code() == 1


def test_an_expired_session_before_the_first_order_says_to_sign_in(workspace):
    class Expired:
        def server_today(self):
            raise ApiError(api_workflow.NOT_LOGGED_IN_MESSAGE, code=600207)

    report = api_workflow.run(commit=True, client=Expired())

    assert report.aborted is True
    assert "登录" in report.abort_reason


def test_the_run_is_journalled_and_reported_to_disk(workspace):
    report = api_workflow.run(commit=True, client=FakePortal())
    saved = json.loads(next((workspace / "runs").glob("*/report.json")).read_text(encoding="utf-8"))

    assert saved["totals"]["succeeded"] == 2
    assert saved["totals"]["rows_filled"] == 2
    assert saved["dry_run"] is False
