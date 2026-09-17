from src.report import OrderResult, RunReport


def test_totals_summarise_every_order_status():
    report = RunReport()
    report.orders = [
        OrderResult("A1", status="succeeded", rows_filled=4),
        OrderResult("A2", status="skipped"),
        OrderResult("A3", status="failed", rows_filled=1, rows_failed=2),
    ]
    assert report.totals() == {
        "orders": 3,
        "succeeded": 1,
        "skipped": 1,
        "failed": 1,
        "rows_filled": 5,
    }


def test_empty_report_totals_are_zero():
    assert RunReport().totals()["orders"] == 0


def test_exit_code_is_zero_when_every_order_succeeded():
    report = RunReport()
    report.orders = [OrderResult("A1", status="succeeded"), OrderResult("A2", status="skipped")]
    assert report.exit_code() == 0


def test_exit_code_is_non_zero_when_an_order_failed():
    report = RunReport()
    report.orders = [OrderResult("A1", status="failed")]
    assert report.exit_code() == 1


def test_exit_code_reports_an_abort_even_with_no_orders():
    """Regression: an aborted run used to look like a clean, empty day."""
    report = RunReport()
    report.aborted = True
    report.abort_code = 2
    assert report.exit_code() == 2
    assert report.totals()["orders"] == 0
