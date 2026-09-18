"""Orchestration through the portal's JSON endpoints.

The click-driven workflow opens four pages and types into a table cell by cell.
This one asks the portal the same questions over its own JSON endpoints, so a
run finishes in seconds, needs no visible browser, and can read its work back
instead of assuming the clicks landed.

A browser is still needed for one thing: the request signature. ``SIGN`` and
``login-token`` live in the portal's ``localStorage``, so they are read once and
cached next to the other run data. The first run of a session may flash a window
for a second; every run after that stays quiet.
"""

from __future__ import annotations

import json
import traceback
from datetime import date
from pathlib import Path
from typing import Any, Callable

from . import api
from .api import ApiError, Credentials, PortalApi, read_credentials
from .config import load_config
from .errors import INTERRUPTED_MESSAGE, explain
from .paths import config_dir
from .report import OrderResult, RunContext, RunReport
from .state import append as journal_append
from .state import load_completed

#: Cached signing values. Outside the repository, like every other run artifact.
SESSION_FILE_NAME = "session.json"

DEFAULT_BOX_CODE = 1

NOT_LOGGED_IN_MESSAGE = api.NOT_LOGGED_IN_MESSAGE


def credentials_path() -> Path:
    return config_dir() / SESSION_FILE_NAME


def load_cached(path: Path | None = None) -> Credentials | None:
    """Return the stored signing values, or ``None`` if there are none."""
    target = path or credentials_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    sign = str(raw.get("sign") or "")
    token = str(raw.get("token") or "")
    if not sign or not token:
        return None
    return Credentials(sign=sign, token=token, skew_ms=int(raw.get("skew_ms") or 0))


def store(credentials: Credentials, path: Path | None = None) -> Path:
    """Cache the signing values so later runs need no browser at all."""
    target = path or credentials_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"sign": credentials.sign, "token": credentials.token, "skew_ms": credentials.skew_ms}
        ),
        encoding="utf-8",
    )
    try:
        target.chmod(0o600)
    except OSError:  # not every filesystem supports it, and it is only hygiene
        pass
    return target


def forget(path: Path | None = None) -> None:
    """Drop the cache, so the next run is forced to read a fresh session."""
    target = path or credentials_path()
    try:
        target.unlink()
    except OSError:
        pass


def capture_from_browser(*, log: Callable[[str], None] = lambda _: None, base_url: str | None = None) -> Credentials:
    """Open the stored profile once and read the signing values out of it.

    The window is minimised as soon as the page is up and closed immediately
    after, so the interruption is a flicker rather than a session.
    """
    from . import browser as browser_module

    config = load_config()
    timing = config.get("timing", {})
    timeout = int(timing.get("nav_timeout_ms", 30000))

    log("reading the session from the browser profile ...")
    session = browser_module.launch(headless=False)
    try:
        page = session.page
        page.goto(base_url or config["base_url"], wait_until="domcontentloaded", timeout=timeout)
        if browser_module.looks_logged_out(page.url, page):
            raise ApiError(NOT_LOGGED_IN_MESSAGE)
        if config.get("behavior", {}).get("minimize_window", True):
            browser_module.minimize(session)
        return api.read_credentials(page)
    finally:
        session.close()


def connect(
    credentials: Credentials | None = None,
    *,
    capture: Callable[..., Credentials] | None = None,
    log: Callable[[str], None] = lambda _: None,
) -> PortalApi:
    """Return a client the portal will accept.

    A cached session is tried first; only an outright rejection sends us back to
    the browser, which keeps the common case free of windows.
    """
    if credentials is not None:
        return PortalApi(credentials)

    cached = load_cached()
    if cached is not None:
        client = PortalApi(cached)
        try:
            client.server_today()
        except ApiError as exc:
            if exc.code not in api.NOT_LOGGED_IN_CODES:
                raise
            log("the cached session was rejected — reading a fresh one")
            forget()
        else:
            log("using the cached session")
            return client

    fresh = (capture or capture_from_browser)(log=log)
    client = PortalApi(fresh)
    # Proved before the run starts, so a bad capture fails here rather than
    # half-way through an order.
    client.server_today()
    store(fresh)
    log("session refreshed")
    return client


def run(
    *,
    commit: bool = False,
    limit: int | None = None,
    only_order: str | None = None,
    log_sink=None,
    credentials: Credentials | None = None,
    capture: Callable[..., Credentials] | None = None,
    client: Any = None,
) -> RunReport:
    """Clear every order still waiting for UPI maintenance."""
    config = load_config()
    box_code = int(config.get("behavior", {}).get("box_code", DEFAULT_BOX_CODE))

    context = RunContext(sink=log_sink)
    report = RunReport(dry_run=not commit)

    try:
        context.log(f"mode: {'COMMIT' if commit else 'DRY RUN'} (api)")

        api_client = client or connect(credentials, capture=capture, log=context.log)
        today = api_client.server_today()
        context.log(f"portal date: {today}")

        # Deliberately unfiltered by date. An order notice is dated the day
        # before it is due, so asking for "orders dated today" quietly returns
        # nothing while work is still outstanding. Being still flagged unexecuted
        # is the condition that actually means "this needs doing".
        orders = api_client.pending_orders()
        if only_order:
            orders = [order for order in orders if str(order.get("sheetId")) == str(only_order)]
        if limit:
            orders = orders[:limit]

        context.log(f"found {len(orders)} order(s) waiting")
        if not orders:
            context.log("nothing to do")
            return report

        completed = load_completed(today)
        for position, order in enumerate(orders, start=1):
            order_no = str(order.get("sheetId") or "")
            result = OrderResult(order_no=order_no)
            report.orders.append(result)

            if order_no in completed:
                result.status = "skipped"
                context.log(f"[{position}/{len(orders)}] {order_no}: already done today")
                continue

            context.log(f"[{position}/{len(orders)}] {order_no}: reading")
            try:
                _process(api_client, order, today, box_code, commit, result, context)
            except Exception as exc:
                result.status = "failed"
                result.error = str(exc)
                context.log(f"[{position}/{len(orders)}] {order_no}: failed — {exc}")

            # A dry run leaves no trace in the journal: recording it would make
            # the next real run skip orders that were never written.
            if commit:
                journal_append(
                    {
                        "order_no": order_no,
                        "status": result.status,
                        "rows_filled": result.rows_filled,
                        "rows_skipped": result.rows_skipped,
                        "rows_failed": result.rows_failed,
                        "dry_run": False,
                        "error": result.error,
                    },
                    today,
                )

        return report
    except KeyboardInterrupt:
        report.aborted = True
        report.abort_code = 130
        report.abort_reason = INTERRUPTED_MESSAGE
        context.log("interrupted by the operator")
        context.log_detail(traceback.format_exc())
        return report
    except Exception as exc:
        report.aborted = True
        report.abort_reason = explain(exc)
        first_line = next(
            (line for line in str(exc).splitlines() if line.strip()), exc.__class__.__name__
        )
        context.log(f"aborted: {first_line}")
        context.log_detail(traceback.format_exc())
        return report
    finally:
        path = context.save(report)
        _print_summary(context, report)
        context.log(f"artifacts: {path.parent}")


def _process(
    api_client: Any,
    order: dict,
    today: date,
    box_code: int,
    commit: bool,
    result: OrderResult,
    context: RunContext,
) -> None:
    """Plan one order's box codes, write them when asked, then read them back."""
    rows = api_client.order_rows(order)
    if not rows:
        result.status = "failed"
        result.error = "没有商品行"
        context.log("  the order has no product rows")
        return

    allocated = [row for row in rows if float(row.get("realQty") or 0) > 0]
    result.rows_filled = len(allocated)
    result.rows_skipped = len(rows) - len(allocated)
    context.log(f"  {len(rows)} row(s), {len(allocated)} to label")

    if not commit:
        result.status = "succeeded"
        context.log("  dry run — nothing written")
        return

    api_client.save_boxes(api.plan_box_entries(rows, today, box_code))

    # The portal answers 200000 whether or not every row landed, so the only
    # trustworthy confirmation is to ask it again.
    remaining = api.unfinished_rows(api_client.verify_boxes(order), box_code)
    if remaining:
        result.status = "failed"
        result.rows_failed = len(remaining)
        result.error = f"{len(remaining)} 行没写入"
        context.log(f"  {len(remaining)} row(s) did not take the box code")
    else:
        result.status = "succeeded"
        context.log(f"  verified: {len(allocated)} row(s) now carry box code {box_code}")


def _print_summary(context: RunContext, report: RunReport) -> None:
    totals = report.totals()
    context.log("-" * 64)
    if report.aborted:
        context.log(f"ABORTED — {report.abort_reason}")
    context.log(
        "orders={orders}  succeeded={succeeded}  skipped={skipped}  "
        "failed={failed}  rows_filled={rows_filled}".format(**totals)
    )
    for order in report.orders:
        if order.status == "failed":
            context.log(f"  FAILED {order.order_no}: {order.error}")
