"""A miniature stand-in for the supplier portal, served over real HTTP.

It reproduces the four pages and the behaviour that matters: the order list is
hidden until the search runs, an order opens a detail page, the detail page
leads to the box-code table, and saving posts the values back to the server so
a test can assert on what was actually submitted.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class PortalState:
    def __init__(self, orders: list[str], rows: int) -> None:
        self.orders = list(orders)
        self.rows = {order: ["" for _ in range(rows)] for order in orders}
        self.saved: list[dict] = []


def _page(title: str, body: str) -> bytes:
    return (
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
        f"<title>{title}</title></head><body>{body}</body></html>"
    ).encode("utf-8")


def _query_page(state: PortalState) -> bytes:
    links = "".join(
        f"<tr><td><a href='/orderDetail?order={order}'>{order}</a></td></tr>"
        for order in state.orders
    )
    body = f"""
    <h3>UPI 维护</h3>
    <input id="date" placeholder="请选择日期">
    <button onclick="document.getElementById('results').style.display='table'">查询</button>
    <table id="results" style="display:none"><tbody>{links}</tbody></table>
    """
    return _page("UPI 维护", body)


def _detail_page(order: str) -> bytes:
    body = f"<h3>订单明细 {order}</h3><a href='/boxCode?order={order}'>订货审批单</a>"
    return _page(f"订单明细 {order}", body)


def _box_page(state: PortalState, order: str) -> bytes:
    rows = "".join(
        f"<tr><td>2026-09-17</td><td><input value='{value}'></td></tr>"
        for value in state.rows[order]
    )
    body = f"""
    <h3>箱码维护 {order}</h3>
    <table><tbody>{rows}</tbody></table>
    <button onclick="save()">保存</button>
    <script>
      function save() {{
        const values = [...document.querySelectorAll('tbody input')].map(i => i.value);
        fetch('/save?order={order}&values=' + encodeURIComponent(values.join(',')));
      }}
    </script>
    """
    return _page(f"箱码维护 {order}", body)


@contextmanager
def serve(orders: list[str], rows: int = 3):
    state = PortalState(orders, rows)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)

            if parsed.path == "/upiMaintain":
                payload = _query_page(state)
            elif parsed.path == "/orderDetail":
                payload = _detail_page(query.get("order", [""])[0])
            elif parsed.path == "/boxCode":
                payload = _box_page(state, query.get("order", [""])[0])
            elif parsed.path == "/save":
                order = query.get("order", [""])[0]
                values = query.get("values", [""])[0].split(",")
                state.rows[order] = values
                state.saved.append({"order": order, "values": values})
                payload = b"ok"
            elif parsed.path == "/__state":
                payload = json.dumps(
                    {"rows": state.rows, "saved": state.saved}, ensure_ascii=False
                ).encode("utf-8")
            else:
                self.send_response(404)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
