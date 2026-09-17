"""Entry point for the supplier portal box-code automation.

Usage::

    python main.py login       # one-time sign-in, profile is reused afterwards
    python main.py calibrate   # capture the real page structure
    python main.py run         # dry run: list what would change
    python main.py run --commit
"""

from __future__ import annotations

import argparse
import sys

from src import browser as browser_module
from src.calibrate import run as run_calibration
from src.config import load_config
from src.paths import browser_profile_dir, config_dir, ensure_dirs


def command_login(notify=input) -> int:
    """Open the portal so the operator can sign in once on this device."""
    ensure_dirs()
    config = load_config()
    session = browser_module.launch(headless=False)
    try:
        page = session.page
        page.goto(config["base_url"], wait_until="domcontentloaded", timeout=60000)
        if browser_module.looks_logged_out(page.url, page):
            print("sign in inside the browser window (SMS verification is expected once).")
            notify("press Enter once you are logged in ... ")
        else:
            print("already signed in — the stored profile is still valid.")
        print(f"profile: {browser_profile_dir()}")
        print("keep this directory; deleting it forces a new SMS verification.")
    finally:
        session.close()
    return 0


def command_run(args: argparse.Namespace) -> int:
    from src.workflow import run as run_workflow

    report = run_workflow(commit=args.commit, limit=args.limit, only_order=args.order)
    return 1 if any(order.status == "failed" for order in report.orders) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="supplier-portal-automation", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("login", help="one-time sign-in into a persistent profile")

    subparsers.add_parser("calibrate", help="capture the real page structure")

    run_parser = subparsers.add_parser("run", help="process the day's orders")
    run_parser.add_argument("--commit", action="store_true", help="actually write data")
    run_parser.add_argument("--limit", type=int, default=None, help="process at most N orders")
    run_parser.add_argument("--order", default=None, help="process a single order number")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "login":
        return command_login()
    if args.command == "calibrate":
        run_calibration()
        return 0
    return command_run(args)


if __name__ == "__main__":
    print(f"config directory: {config_dir()}", file=sys.stderr)
    raise SystemExit(main())
