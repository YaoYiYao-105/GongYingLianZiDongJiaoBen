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
