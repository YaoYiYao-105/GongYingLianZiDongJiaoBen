"""Entry point for the supplier portal box-code automation.

Usage::

    python main.py login       # one-time sign-in, profile is reused afterwards
    python main.py calibrate   # capture the real page structure
    python main.py run         # dry run: list what would change
    python main.py run --commit
    python main.py run --mode browser --commit   # fall back to clicking the pages
"""

from __future__ import annotations

import argparse
import sys

from src import api_workflow
from src import browser as browser_module
from src.calibrate import run as run_calibration
from src.config import load_config
from src.errors import explain
from src.paths import browser_profile_dir, ensure_dirs
from src.workflow import DEFAULT_MODE


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
        try:
            api_workflow.store(api_workflow.read_credentials(page))
            print("session cached — maintenance runs will not need a browser window.")
        except Exception as exc:
            print(f"could not cache the session yet ({exc}); it will be read again on the first run.")
        print(f"profile: {browser_profile_dir()}")
        print("keep this directory; deleting it forces a new SMS verification.")
    finally:
        session.close()
    return 0


def command_run(args: argparse.Namespace) -> int:
    from src.workflow import run as run_workflow

    report = run_workflow(
        commit=args.commit, limit=args.limit, only_order=args.order, mode=args.mode
    )
    if report.aborted:
        print(f"\n运行中止：{report.abort_reason}", file=sys.stderr)
    return report.exit_code()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="supplier-portal-automation", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("login", help="one-time sign-in into a persistent profile")

    subparsers.add_parser("calibrate", help="capture the real page structure")

    run_parser = subparsers.add_parser("run", help="process the day's orders")
    run_parser.add_argument("--commit", action="store_true", help="actually write data")
    run_parser.add_argument("--limit", type=int, default=None, help="process at most N orders")
    run_parser.add_argument("--order", default=None, help="process a single order number")
    run_parser.add_argument(
        "--mode",
        choices=("api", "browser"),
        default=DEFAULT_MODE,
        help="drive the portal through its JSON endpoints (default) or by clicking",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "login":
            return command_login()
        if args.command == "calibrate":
            run_calibration()
            return 0
        return command_run(args)
    except KeyboardInterrupt:
        print("\n已中断，已完成的进度保存在 state 目录。", file=sys.stderr)
        return 130
    except Exception as exc:
        # Nothing should reach here, but an operator must never be shown a
        # traceback for a problem they cannot act on.
        print(f"\n运行失败：{explain(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
