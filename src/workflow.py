"""Orchestration: query the day's orders, then clear each one's box codes."""

from __future__ import annotations

from . import browser as browser_module
from .config import load_config
from .report import OrderResult, RunContext, RunReport
from .state import append as journal_append
from .state import load_completed
from .steps import box_code, order_flow, upi_query


def run(
    *,
    commit: bool = False,
    limit: int | None = None,
    only_order: str | None = None,
    log_sink=None,
) -> RunReport:
    config = load_config()
    selectors = config["steps"]
    timing = config.get("timing", {})
    delay = int(timing.get("action_delay_ms", 450))
    jitter = int(timing.get("action_jitter_ms", 350))
    timeout = int(timing.get("nav_timeout_ms", 30000))

    context = RunContext(sink=log_sink)
    report = RunReport(dry_run=not commit)
    session = browser_module.launch(headless=False)

    def pause() -> None:
        browser_module.human_pause(delay, jitter)

    try:
        page = session.page
        context.log(f"mode: {'COMMIT' if commit else 'DRY RUN'}")
        page.goto(config["base_url"], wait_until="domcontentloaded", timeout=timeout)

        if browser_module.looks_logged_out(page.url, page):
            context.log("not logged in — run `python main.py login` first")
            raise SystemExit(2)

        if config.get("behavior", {}).get("minimize_window", True):
            if browser_module.minimize(session):
                context.log("browser window minimised — it keeps working in the background")

        context.log("setting today's date and searching ...")
        upi_query.set_today(page, selectors["upi_query"], timeout)
        upi_query.run_query(page, selectors["upi_query"], timeout)

        orders = upi_query.collect_order_numbers(page, selectors["upi_query"], timeout)
        if only_order:
            orders = [number for number in orders if number == only_order]
        if limit:
            orders = orders[:limit]

        context.log(f"found {len(orders)} order(s)")
        if not orders:
            context.log("nothing to do")
            return report

        completed = load_completed()
        for position, order_no in enumerate(orders, start=1):
            result = OrderResult(order_no=order_no)
            report.orders.append(result)

            if order_no in completed:
                result.status = "skipped"
                context.log(f"[{position}/{len(orders)}] {order_no}: already done today")
                continue

            context.log(f"[{position}/{len(orders)}] {order_no}: opening")
            try:
                page.goto(config["base_url"], wait_until="domcontentloaded", timeout=timeout)
                order_flow.open_order_detail(page, order_no, selectors["order_flow"], timeout)
                order_flow.open_approval_form(page, selectors["order_flow"], timeout)

                stats = box_code.fill_rows(
                    page,
                    selectors["box_code"],
                    commit=commit,
                    log=context.log,
                    pause=pause,
                    timeout_ms=timeout,
                )
                result.rows_filled = stats.filled
                result.rows_skipped = stats.skipped
                result.rows_failed = stats.failed

                if stats.failed:
                    result.status = "failed"
                    result.error = f"{stats.failed} row(s) failed"
                else:
                    result.status = "succeeded"

                context.screenshot(page, f"{order_no}-done")
            except Exception as exc:
                result.status = "failed"
                result.error = str(exc)
                context.log(f"[{position}/{len(orders)}] {order_no}: failed — {exc}")
                browser_module.restore(session)
                context.screenshot(page, f"{order_no}-failed")

            journal_append(
                {
                    "order_no": order_no,
                    "status": result.status,
                    "rows_filled": result.rows_filled,
                    "rows_skipped": result.rows_skipped,
                    "rows_failed": result.rows_failed,
                    "dry_run": not commit,
                    "error": result.error,
                }
            )

        return report
    finally:
        path = context.save(report)
        _print_summary(context, report)
        context.log(f"artifacts: {path.parent}")
        session.close()


def _print_summary(context: RunContext, report: RunReport) -> None:
    totals = report.totals()
    context.log("-" * 64)
    context.log(
        "orders={orders}  succeeded={succeeded}  skipped={skipped}  "
        "failed={failed}  rows_filled={rows_filled}".format(**totals)
    )
    for order in report.orders:
        if order.status == "failed":
            context.log(f"  FAILED {order.order_no}: {order.error}")
