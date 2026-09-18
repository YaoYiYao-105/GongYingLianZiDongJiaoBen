"""Signed JSON client for the portal's UPI endpoints.

Driving the UPI pages means clicking one editable cell per product, per order.
The portal's own web client talks to plain JSON endpoints instead, so this
module reproduces that conversation: same URLs, same body shapes, same md5
request signature.

The signature is built from the method, the path, the serialised parameters and
body, a token the portal keeps in ``localStorage`` under ``SIGN``, and a
rearrangement of the millisecond timestamp. Nothing here is invented — the
portal's client computes exactly this, so the server accepts it as ours.

Only the credentials have to come out of a signed-in browser; the endpoints
themselves answer ordinary HTTPS requests. The calls below therefore run on the
standard library: no browser, no cookie jar, no visible window.

Three details are worth remembering because the portal does not use the obvious
names:

* the search date range travels as ``orderTimeStart`` / ``orderTimeEnd`` — an
  ``orderTime`` array is accepted by the server and then ignored;
* ``flag`` is compared as a string, and ``"2"`` is the value that means "not
  executed yet" — the only state the maintenance page, and the server behind
  it, will accept a box-code write for;
* save responses arrive as HTTP 200 with a non-200000 ``code``, so the body has
  to be inspected rather than the status line.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

API_BASE = "https://glmh.yonghui.cn"

#: ``localStorage`` keys the portal's client signs with.
SIGN_KEY = "SIGN"
TOKEN_KEY = "login-token"
SKEW_KEY = "sign-diff"

#: The portal answers 200000 for success, and this code specifically for an
#: expired session — which the operator can fix by signing in again.
SUCCESS_CODE = 200000
NOT_LOGGED_IN_CODES = frozenset({600207, 8001001, 8000020})

#: ``flag`` on an order notice. ``"2"`` is "not executed yet", which is both the
#: query filter for outstanding work and the server-side precondition for
#: writing box codes.
FLAG_PENDING = "2"

#: ``status`` on an order notice once its UPI data has been submitted.
STATUS_UPI_SUBMITTED = 100

NOT_LOGGED_IN_MESSAGE = "登录状态已失效，请重新登录后再试一次。"


class ApiError(RuntimeError):
    """A response the portal refused, or one we could not make sense of."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Credentials:
    """The three values the portal's request signature needs."""

    sign: str
    token: str
    skew_ms: int = 0


def _is_empty(value: Any) -> bool:
    """Mirror of the portal's ``isEmpty`` helper."""
    if value is None:
        return True
    if isinstance(value, dict):
        return not value
    if isinstance(value, (str, list, tuple)):
        return len(value) == 0
    return False


def param_tamp(params: dict[str, Any] | None) -> str:
    """Serialise query parameters the way the portal's signer does.

    Keys are sorted, values are concatenated as ``key=value`` with no
    separator, and empty ones are dropped.
    """
    if not params:
        return ""
    parts = []
    for key in sorted(params):
        value = params[key]
        if isinstance(value, (str, dict, list, type(None))) and _is_empty(value):
            continue
        parts.append(f"{key}={value}")
    return "".join(parts)


def data_tamp(data: Any) -> str:
    """Serialise a request body the way the portal's signer does."""
    if _is_empty(data):
        return ""
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def timestamp_tamp(timestamp_ms: int) -> str:
    """Rearrange the timestamp: sort its digits, then keep the even positions."""
    digits = sorted(str(int(timestamp_ms)))
    return "".join(digits[index] for index in range(0, len(digits), 2))


def build_sign_headers(
    credentials: Credentials,
    *,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    data: Any = None,
    now_ms: int | None = None,
) -> dict[str, str]:
    """Return the headers that authenticate one call.

    ``now_ms`` exists so tests can pin the timestamp; production callers should
    leave it alone.
    """
    moment = int(now_ms if now_ms is not None else time.time() * 1000) + credentials.skew_ms
    joined = method.upper()
    joined += path if path.startswith("/") else f"/{path}"
    joined += param_tamp(params)
    joined += data_tamp(data)
    joined += credentials.sign
    joined += timestamp_tamp(moment)

    return {
        "timestamp": str(moment),
        "sign": hashlib.md5(joined.encode("utf-8")).hexdigest(),
        TOKEN_KEY: credentials.token,
        "Content-Type": "application/json;charset=UTF-8",
    }


def unwrap_stored(value: str | None) -> str:
    """Undo the JSON encoding the portal applies before storing a value.

    ``localStorage`` holds ``"abc"`` with quotes (it stores JSON), while the
    signer expects ``abc``.
    """
    if value is None:
        return ""
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return value
    return parsed if isinstance(parsed, str) else str(parsed)


def read_credentials(page: Any) -> Credentials:
    """Read the signing values out of a signed-in page's ``localStorage``."""
    raw = page.evaluate(
        """(keys) => Object.fromEntries(keys.map((k) => [k, localStorage.getItem(k)]))""",
        [SIGN_KEY, TOKEN_KEY, SKEW_KEY],
    )
    credentials = Credentials(
        sign=unwrap_stored(raw.get(SIGN_KEY)),
        token=unwrap_stored(raw.get(TOKEN_KEY)),
        skew_ms=int(unwrap_stored(raw.get(SKEW_KEY)) or 0),
    )
    if not credentials.sign or not credentials.token:
        raise ApiError(NOT_LOGGED_IN_MESSAGE)
    return credentials


def today_from(payload: dict[str, Any]) -> date:
    """Pull the portal's own idea of today out of a ``/common/getTime`` reply."""
    stamp = (payload.get("result") or {}).get("nowDate")
    if stamp:
        try:
            return date.fromisoformat(str(stamp)[:10])
        except ValueError:
            pass
    return date.today()


def plan_box_entries(
    rows: list[dict[str, Any]], today: date, box_code: int = 1
) -> list[dict[str, Any]]:
    """Build the ``upiBoxs`` body for one order's rows.

    Reproduces what the maintenance page sends when the operator walks the
    table and saves:

    * a row with an allocation gets today's date as its production date, an
      expiry date ``qaDays`` later, and the box code;
    * a row without an allocation is sent back empty — the page clears the box
      code there too, because a row that was never allocated has nothing to
      label.
    """
    entries: list[dict[str, Any]] = []
    for row in rows:
        real_qty = float(row.get("realQty") or 0)
        entry: dict[str, Any] = {
            "sheetId": row.get("sheetId", ""),
            "refSheetId": row.get("refSheetId", ""),
            "goodsId": row.get("goodsId"),
            "realQty": real_qty,
        }
        if real_qty > 0:
            entry["procDate"] = today.isoformat()
            entry["overDate"] = (today + timedelta(days=int(row.get("qaDays") or 0))).isoformat()
            entry["upiBoxNo"] = box_code
        else:
            entry["procDate"] = ""
            entry["overDate"] = ""
            entry["upiBoxNo"] = ""
        entries.append(entry)
    return entries


def unfinished_rows(rows: list[dict[str, Any]], box_code: int = 1) -> list[dict[str, Any]]:
    """Allocated rows that still lack a box code or a production date.

    Used to check a save by reading the order back, rather than trusting that a
    200000 reply meant every row landed. The production date is checked as well
    because a row can keep its box code while the date is refused, and it is the
    date the UPI submission actually depends on.
    """
    expected = str(box_code)
    return [
        row
        for row in rows
        if float(row.get("realQty") or 0) > 0
        and (str(row.get("upiBoxNo") or "") != expected or not row.get("procDate"))
    ]


def _send(url: str, *, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, str]:
    """POST ``body`` and return ``(status, text)``. Swapped out in tests."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:  # 4xx/5xx still carry a body worth reading
        return exc.code, exc.read().decode("utf-8", errors="replace")


class PortalApi:
    """The portal calls this tool needs, in order."""

    def __init__(
        self,
        credentials: Credentials,
        *,
        base_url: str = API_BASE,
        timeout: float = 30.0,
        retries: int = 3,
        send: Callable[..., tuple[int, str]] = _send,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._credentials = credentials
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._retries = max(1, retries)
        self._send = send
        self._sleep = sleep

    def _post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = body if body is not None else {}
        # Serialised once, here, so the bytes that are signed are the bytes that
        # go out. The headers are rebuilt per attempt because the timestamp is
        # part of the signature and a stale one is rejected.
        serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        url = f"{self._base_url}{path}"
        last: ApiError | None = None

        for attempt in range(1, self._retries + 1):
            headers = build_sign_headers(
                self._credentials, method="POST", path=path, params={}, data=payload
            )
            try:
                status, text = self._send(url, headers=headers, body=serialized, timeout=self._timeout)
            except Exception as exc:
                last = ApiError(f"连接后台失败：{exc}")
            else:
                if status >= 500:
                    # Seen in practice as an intermittent 502 from the gateway.
                    last = ApiError(f"后台返回了 HTTP {status}", code=status)
                elif status != 200:
                    raise ApiError(f"后台返回了 HTTP {status}", code=status)
                else:
                    return self._decode(text)

            if attempt < self._retries:
                self._sleep(1.5 * attempt)

        raise last if last is not None else ApiError("请求后台失败。")

    def _decode(self, text: str) -> dict[str, Any]:
        try:
            decoded = json.loads(text)
        except ValueError as exc:  # a proxy error page, say
            raise ApiError("后台返回的内容无法解析，请稍后重试。") from exc

        code = decoded.get("code")
        if code in NOT_LOGGED_IN_CODES:
            raise ApiError(NOT_LOGGED_IN_MESSAGE, code=code)
        if code != SUCCESS_CODE:
            raise ApiError(str(decoded.get("message") or f"后台返回错误码 {code}"), code=code)
        return decoded

    # ------------------------------------------------------------------ calls
    def server_today(self) -> date:
        """The portal's date, which decides what ``orderTimeStart`` means."""
        return today_from(self._post("/common/getTime", {}))

    def pending_orders(
        self, *, day: date | None = None, size: int = 200, max_pages: int = 25
    ) -> list[dict[str, Any]]:
        """Order notices still waiting for UPI maintenance.

        ``day`` filters on the order date, the same field the maintenance page's
        date picker sends. Left out, the portal returns its whole history —
        which is what we want, see :func:`src.api_workflow.run`.

        Pages until the portal says there is nothing left, so a backlog larger
        than one page is never silently truncated.
        """
        body: dict[str, Any] = {"size": size, "flag": FLAG_PENDING}
        if day is not None:
            stamp = day.isoformat()
            body["orderTimeStart"] = stamp
            body["orderTimeEnd"] = stamp

        orders: list[dict[str, Any]] = []
        for page_number in range(1, max_pages + 1):
            decoded = self._post("/upi/searchTotal", {**body, "page": page_number})
            page = decoded.get("page") or {}
            batch = list(page.get("result") or [])
            orders.extend(batch)
            if not batch or len(orders) >= (page.get("totalNum") or 0):
                break
        return orders

    def order_rows(self, order: dict[str, Any]) -> list[dict[str, Any]]:
        """The product rows behind one order notice, ready to be planned.

        One notice covers one store, so an order spreads over as many
        ``getUpiBoxDetailInfo`` calls as it has stores.
        """
        sheet_id = order.get("sheetId", "")
        flag = order.get("flag")
        detail = self._post("/upi/getUpiDetailInfo", {"sheetId": sheet_id, "flag": flag})
        notices = detail.get("result") or []
        if not notices:
            raise ApiError(f"订单 {sheet_id} 查不到明细。")

        rows: list[dict[str, Any]] = []
        for notice in notices:
            payload = {
                "refSheetId": notice.get("refSheetId", ""),
                "sheetId": sheet_id,
                "flag": flag,
            }
            boxes = self._post("/upi/getUpiBoxDetailInfo", payload)
            rows.extend(boxes.get("result") or [])
        return rows

    def save_boxes(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Write one order's box codes back."""
        return self._post("/upi/saveUpi", {"upiBoxs": entries})

    def verify_boxes(self, order: dict[str, Any]) -> list[dict[str, Any]]:
        """Re-read an order's rows, so a save can be checked rather than assumed."""
        return self.order_rows(order)
