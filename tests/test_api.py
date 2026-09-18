"""The signed-JSON client, exercised without touching the portal.

The signature is the part that has to be exactly right: a single misplaced
character makes every call fail with an opaque server error, so the tests below
pin the byte sequence rather than only the shape of the output. Everything else
here is bookkeeping — which endpoint receives which body, and what happens when
the gateway answers 502.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest

from src import api

CREDENTIALS = api.Credentials(sign="SIGNSIGN", token="TOKEN", skew_ms=0)
PINNED_NOW_MS = 1700000000000


def success(payload: dict | None = None) -> tuple[int, str]:
    body = {"code": api.SUCCESS_CODE, "message": "success", "result": None}
    body.update(payload or {})
    return 200, json.dumps(body, ensure_ascii=False)


class Transport:
    """Stands in for ``_send``: records calls, replays scripted replies."""

    def __init__(self, replies) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def __call__(self, url, *, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": body.decode("utf-8")})
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    @property
    def last_body(self) -> dict:
        return json.loads(self.calls[-1]["body"])


def build(replies, **kwargs) -> tuple[api.PortalApi, Transport]:
    transport = Transport(replies)
    client = api.PortalApi(CREDENTIALS, send=transport, sleep=lambda _: None, **kwargs)
    return client, transport


# ------------------------------------------------------------------ signature
def test_param_tamp_sorts_keys_and_drops_empties():
    assert api.param_tamp({"b": 2, "a": 1}) == "a=1b=2"
    assert api.param_tamp({"a": "", "b": None, "c": [], "d": {}}) == ""
    assert api.param_tamp({"a": 0, "b": False}) == "a=0b=False"
    assert api.param_tamp(None) == ""


def test_data_tamp_serialises_compactly_and_keeps_chinese():
    assert api.data_tamp({"page": 1, "size": 10}) == '{"page":1,"size":10}'
    assert api.data_tamp({"name": "测试商品"}) == '{"name":"测试商品"}'
    assert api.data_tamp({}) == ""
    assert api.data_tamp(None) == ""


def test_timestamp_tamp_sorts_digits_and_keeps_even_positions():
    assert api.timestamp_tamp(1700000000000) == "0000007"
    assert api.timestamp_tamp(1234) == "13"
    # sorted digits of 9876543210 are 0123456789; every other one is kept
    assert api.timestamp_tamp(9876543210) == "02468"


def test_signature_matches_a_pinned_byte_sequence():
    """The exact string the digest is taken over, spelled out in full."""
    headers = api.build_sign_headers(
        CREDENTIALS,
        method="post",
        path="upi/searchTotal",
        params={},
        data={"page": 1, "size": 10},
        now_ms=PINNED_NOW_MS,
    )
    joined = 'POST/upi/searchTotal{"page":1,"size":10}SIGNSIGN0000007'
    assert headers["sign"] == hashlib.md5(joined.encode()).hexdigest()
    assert headers["sign"] == "977c8ae028e352a0b0e17c555b7a50d7"


def test_signature_places_params_before_body():
    headers = api.build_sign_headers(
        CREDENTIALS,
        method="POST",
        path="/upi/searchTotal",
        params={"orderTimeStart": "2026-09-18", "flag": "2"},
        data={"page": 1},
        now_ms=PINNED_NOW_MS,
    )
    joined = 'POST/upi/searchTotalflag=2orderTimeStart=2026-09-18{"page":1}SIGNSIGN0000007'
    assert headers["sign"] == hashlib.md5(joined.encode()).hexdigest()


def test_headers_carry_the_session_and_a_fresh_timestamp():
    headers = api.build_sign_headers(
        CREDENTIALS, method="POST", path="/common/getTime", data={}, now_ms=PINNED_NOW_MS
    )
    assert headers["timestamp"] == str(PINNED_NOW_MS)
    assert headers["login-token"] == "TOKEN"
    assert headers["Content-Type"] == "application/json;charset=UTF-8"
    assert headers["sign"] == "8dbae800457eeec149746b370c8f58fa"


def test_skew_shifts_the_timestamp():
    skewed = api.Credentials(sign="SIGNSIGN", token="TOKEN", skew_ms=242)
    headers = api.build_sign_headers(
        skewed, method="POST", path="/common/getTime", data={}, now_ms=PINNED_NOW_MS
    )
    assert headers["timestamp"] == str(PINNED_NOW_MS + 242)


# ---------------------------------------------------------------- credentials
def test_unwrap_stored_removes_the_json_quoting():
    assert api.unwrap_stored('"abc"') == "abc"
    assert api.unwrap_stored("abc") == "abc"
    assert api.unwrap_stored('"242"') == "242"
    assert api.unwrap_stored(None) == ""


class FakeStorage:
    def __init__(self, values: dict) -> None:
        self.values = values

    def evaluate(self, script, keys):
        return {key: self.values.get(key) for key in keys}


def test_read_credentials_unwraps_what_localstorage_holds():
    page = FakeStorage({"SIGN": '"SIGNSIGN"', "login-token": '"TOKEN"', "sign-diff": '"242"'})
    assert api.read_credentials(page) == CREDENTIALS.__class__(
        sign="SIGNSIGN", token="TOKEN", skew_ms=242
    )


def test_read_credentials_reports_a_signed_out_browser():
    with pytest.raises(api.ApiError) as caught:
        api.read_credentials(FakeStorage({}))
    assert "登录" in str(caught.value)


# ------------------------------------------------------------------- planning
def row(goods_id: int, real_qty: float, qa_days: int) -> dict:
    return {
        "sheetId": "2609180001",
        "refSheetId": "9000000001",
        "goodsId": goods_id,
        "realQty": real_qty,
        "qaDays": qa_days,
    }


def test_plan_stamps_today_and_the_shelf_life_like_the_page_does():
    entries = api.plan_box_entries([row(1001, 2.0, 5), row(1002, 1.0, 7)], date(2026, 9, 18))
    assert entries[0] == {
        "sheetId": "2609180001",
        "refSheetId": "9000000001",
        "goodsId": 1001,
        "realQty": 2.0,
        "procDate": "2026-09-18",
        "overDate": "2026-09-23",
        "upiBoxNo": 1,
    }
    assert entries[1]["overDate"] == "2026-09-25"


def test_plan_clears_rows_without_an_allocation():
    entries = api.plan_box_entries([row(1001, 0, 5)], date(2026, 9, 18))
    assert entries[0]["procDate"] == ""
    assert entries[0]["overDate"] == ""
    assert entries[0]["upiBoxNo"] == ""


def test_plan_accepts_a_different_box_code_and_a_missing_shelf_life():
    entries = api.plan_box_entries([row(1001, 3.0, 0)], date(2026, 9, 18), box_code=2)
    assert entries[0]["upiBoxNo"] == 2
    assert entries[0]["overDate"] == "2026-09-18"


def test_unfinished_rows_only_flags_allocated_rows():
    rows = [
        {**row(1, 2.0, 5), "upiBoxNo": "1", "procDate": "2026-09-18"},
        {**row(2, 3.0, 5), "upiBoxNo": "", "procDate": "2026-09-18"},
        {**row(3, 0, 5), "upiBoxNo": "", "procDate": ""},
    ]
    assert [r["goodsId"] for r in api.unfinished_rows(rows)] == [2]


def test_unfinished_rows_catches_a_missing_production_date():
    rows = [{**row(1, 2.0, 5), "upiBoxNo": "1", "procDate": ""}]
    assert [r["goodsId"] for r in api.unfinished_rows(rows)] == [1]


def test_unfinished_rows_accepts_a_different_box_code():
    rows = [{**row(1, 2.0, 5), "upiBoxNo": "2", "procDate": "2026-09-18"}]
    assert api.unfinished_rows(rows, box_code=2) == []
    assert len(api.unfinished_rows(rows, box_code=1)) == 1


def test_today_from_prefers_the_portal_clock():
    assert api.today_from({"result": {"nowDate": "2026-09-18", "time": "x"}}) == date(2026, 9, 18)
    assert api.today_from({"result": {"nowDate": "not a date"}}) == date.today()
    assert api.today_from({}) == date.today()


# ---------------------------------------------------------------- calls, wire
def test_server_today_reads_the_portal_clock():
    client, transport = build([success({"result": {"nowDate": "2026-09-18"}})])
    assert client.server_today() == date(2026, 9, 18)
    assert transport.calls[0]["url"].endswith("/common/getTime")
    assert transport.last_body == {}


def test_pending_orders_asks_for_todays_unexecuted_sheet():
    client, transport = build([success({"page": {"totalNum": 1, "result": [{"sheetId": "1"}]}})])
    orders = client.pending_orders(day=date(2026, 9, 18))
    assert orders == [{"sheetId": "1"}]
    assert transport.last_body == {
        "page": 1,
        "size": 200,
        # A string, not the number 2 — the portal compares it that way.
        "flag": "2",
        "orderTimeStart": "2026-09-18",
        "orderTimeEnd": "2026-09-18",
    }


def test_pending_orders_pages_until_the_backlog_is_exhausted():
    client, transport = build(
        [
            success({"page": {"totalNum": 3, "result": [{"sheetId": "1"}, {"sheetId": "2"}]}}),
            success({"page": {"totalNum": 3, "result": [{"sheetId": "3"}]}}),
        ]
    )
    orders = client.pending_orders()

    assert [order["sheetId"] for order in orders] == ["1", "2", "3"]
    assert [json.loads(call["body"])["page"] for call in transport.calls] == [1, 2]


def test_pending_orders_stops_when_the_last_page_is_empty():
    client, transport = build(
        [
            success({"page": {"totalNum": 5, "result": [{"sheetId": "1"}]}}),
            success({"page": {"totalNum": 5, "result": []}}),
        ]
    )
    assert len(client.pending_orders()) == 1
    assert len(transport.calls) == 2


def test_pending_orders_omits_the_range_when_no_day_is_given():
    client, transport = build([success({"page": {"result": []}})])
    assert client.pending_orders() == []
    assert "orderTimeStart" not in transport.last_body


def test_order_rows_walks_every_store_notice():
    client, transport = build(
        [
            success({"result": [{"refSheetId": "A"}, {"refSheetId": "B"}]}),
            success({"result": [{"goodsId": 1}]}),
            success({"result": [{"goodsId": 2}, {"goodsId": 3}]}),
        ]
    )
    rows = client.order_rows({"sheetId": "2609180001", "flag": "2"})
    assert [r["goodsId"] for r in rows] == [1, 2, 3]
    assert json.loads(transport.calls[1]["body"]) == {
        "refSheetId": "A",
        "sheetId": "2609180001",
        "flag": "2",
    }


def test_order_rows_reports_an_order_without_notices():
    client, _ = build([success({"result": []})])
    with pytest.raises(api.ApiError) as caught:
        client.order_rows({"sheetId": "2609180001", "flag": "2"})
    assert "2609180001" in str(caught.value)


def test_save_boxes_sends_the_planned_entries():
    entries = api.plan_box_entries([row(1001, 2.0, 5)], date(2026, 9, 18))
    client, transport = build([success()])
    client.save_boxes(entries)
    assert transport.calls[0]["url"].endswith("/upi/saveUpi")
    assert transport.last_body == {"upiBoxs": entries}


# ------------------------------------------------------------- failures, wire
def test_a_502_is_retried_then_succeeds():
    client, transport = build([(502, "bad gateway"), success({"result": {"nowDate": "2026-09-18"}})])
    assert client.server_today() == date(2026, 9, 18)
    assert len(transport.calls) == 2
    # Each attempt is re-signed rather than replayed, because the timestamp is
    # part of the signature and a stale one is rejected.
    for call in transport.calls:
        assert len(call["headers"]["sign"]) == 32
        assert call["headers"]["timestamp"].isdigit()


def test_a_persistent_502_fails_after_the_last_attempt():
    client, transport = build([(502, "bad gateway")] * 3)
    with pytest.raises(api.ApiError) as caught:
        client.server_today()
    assert caught.value.code == 502
    assert len(transport.calls) == 3


def test_a_client_error_is_not_retried():
    client, transport = build([(403, "forbidden")])
    with pytest.raises(api.ApiError) as caught:
        client.server_today()
    assert caught.value.code == 403
    assert len(transport.calls) == 1


def test_a_dropped_connection_is_reported_plainly():
    client, _ = build([ConnectionResetError("connection reset by peer")] * 3)
    with pytest.raises(api.ApiError) as caught:
        client.server_today()
    assert "连接后台失败" in str(caught.value)


def test_an_expired_session_asks_the_operator_to_sign_in():
    body = json.dumps({"code": 600207, "message": "token invalid"})
    client, _ = build([(200, body)])
    with pytest.raises(api.ApiError) as caught:
        client.server_today()
    assert caught.value.code == 600207
    assert "登录" in str(caught.value)


def test_the_servers_own_refusal_is_passed_through():
    body = json.dumps(
        {"code": 500000, "message": "订货通知单状态不为未执行，不能维护", "result": None},
        ensure_ascii=False,
    )
    client, _ = build([(200, body)])
    with pytest.raises(api.ApiError) as caught:
        client.save_boxes([])
    assert caught.value.code == 500000
    assert "不能维护" in str(caught.value)


def test_a_non_json_reply_is_reported_as_such():
    client, _ = build([(200, "<html>gateway</html>")])
    with pytest.raises(api.ApiError) as caught:
        client.server_today()
    assert "无法解析" in str(caught.value)
