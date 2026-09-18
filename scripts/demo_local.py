"""Run the full pipeline against a local mock portal.

This is the honest demonstration: it starts a small HTTP server that mimics the
supplier portal's four pages, points the selector configuration at it, and runs
exactly the same workflow the packaged application runs. No supplier login is
needed, and nothing outside a temporary directory is touched.

    python scripts/demo_local.py              # dry run, writes nothing
    python scripts/demo_local.py --commit     # actually fills the table
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ORDERS = ["260917001", "260917002", "260917003"]
ROWS_PER_ORDER = 4


def write_config(directory: Path, base_url: str) -> None:
    config = {
        "version": 1,
        "base_url": f"{base_url}/upiMaintain",
        "behavior": {"minimize_window": False},
        "timing": {"action_delay_ms": 60, "action_jitter_ms": 60, "nav_timeout_ms": 15000},
        "steps": {
            "upi_query": {
                "date_input": ["placeholder=请选择日期"],
                "query_button": ["role=button[name='查询']"],
                "order_links": ["css=#results a"],
            },
            "order_flow": {"approval_link": ["role=link[name='订货审批单']"]},
            "box_code": {
                "rows": ["css=table tbody tr"],
                "date_cell": ["css=td:nth-child(1)"],
                "box_input": ["css=input"],
                "save_button": ["role=button[name='保存']"],
            },
        },
    }
    (directory / "config").mkdir(parents=True, exist_ok=True)
    (directory / "config" / "selectors.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="actually write to the mock portal")
    args = parser.parse_args()

    from demo.mock_portal import serve

    with tempfile.TemporaryDirectory(prefix="supplier-demo-") as workspace:
        os.environ["SUPPLIER_AUTOMATION_HOME"] = workspace

        with serve(orders=ORDERS, rows=ROWS_PER_ORDER) as (state, base_url):
            write_config(Path(workspace), base_url)

            from src.workflow import run

            print(f"mock portal:  {base_url}/upiMaintain")
            print(f"orders:       {', '.join(ORDERS)}")
            print(f"rows per order: {ROWS_PER_ORDER}")
            print(f"mode:         {'COMMIT' if args.commit else 'DRY RUN'}")
            print("=" * 68)

            # The mock portal serves pages, not JSON, so this demonstrates the
            # click-driven driver. The endpoint-driven one is what the packaged
            # application uses against the real portal.
            report = run(commit=args.commit, mode="browser")

            print("=" * 68)
            print("mock portal state after the run:")
            for order in ORDERS:
                print(f"  {order}: {state.rows[order]}")
            print(f"  submissions received: {len(state.saved)}")

            totals = report.totals()
            expected = ["1"] * ROWS_PER_ORDER
            ok = all(state.rows[order] == expected for order in ORDERS) if args.commit else True
            print("=" * 68)
            print(f"filled {totals['rows_filled']} rows across {totals['orders']} orders")
            print("RESULT:", "PASS" if ok and totals["failed"] == 0 else "FAIL")

            return 0 if ok and totals["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
