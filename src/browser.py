"""Browser lifecycle: persistent profile, channel detection, window control.

The portal decides whether a device is trusted, so the profile directory is
long-lived and reused on every run. Losing it means one more SMS verification.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from .paths import browser_profile_dir, ensure_dirs

#: Preferred browser channels, most widely installed first.
#: Edge ships with Windows and Chrome is common elsewhere; Playwright's bundled
#: Chromium is only a last resort because a branded build looks less unusual.
CHANNEL_PREFERENCE = ("msedge", "chrome", None)


@dataclass
class Session:
    playwright: Playwright
    context: BrowserContext
    page: Page

    def close(self) -> None:
        try:
            self.context.close()
        finally:
            self.playwright.stop()


def launch(headless: bool = False) -> Session:
    """Start Chromium against the persistent profile, headed by default."""
    ensure_dirs()
    playwright = sync_playwright().start()
    errors: list[str] = []

    for channel in CHANNEL_PREFERENCE:
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(browser_profile_dir()),
                channel=channel,
                headless=headless,
                viewport=None,
                args=["--start-maximized"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            return Session(playwright=playwright, context=context, page=page)
        except Exception as exc:  # channel not installed
            errors.append(f"{channel or 'bundled chromium'}: {exc}")

    playwright.stop()
    raise RuntimeError("no usable browser found:\n  " + "\n  ".join(errors))


def human_pause(delay_ms: int, jitter_ms: int) -> None:
    """Sleep for a slightly randomised interval.

    Perfectly regular intervals are a giveaway for automation; a small jitter
    keeps the interaction pattern closer to a person clicking through a form.
    """
    time.sleep((delay_ms + random.uniform(0, max(jitter_ms, 0))) / 1000)


def _set_window_state(session: Session, state: str) -> bool:
    """Drive the window state through CDP; Playwright has no direct API for it."""
    try:
        cdp = session.context.new_cdp_session(session.page)
        window_id = cdp.send("Browser.getWindowForTarget")["windowId"]
        cdp.send(
            "Browser.setWindowBounds",
            {"windowId": window_id, "bounds": {"windowState": state}},
        )
        return True
    except Exception:
        return False


def minimize(session: Session) -> bool:
    """Minimise the automation window so it stays out of the way.

    Safe to do because Playwright already disables background timer throttling,
    renderer backgrounding and occluded-window throttling, so a minimised page
    keeps rendering and responding.
    """
    return _set_window_state(session, "minimized")


def restore(session: Session) -> bool:
    """Bring the automation window back to the foreground after a failure."""
    return _set_window_state(session, "normal")


def looks_logged_out(url: str, page: Page) -> bool:
    """Heuristic check for an SSO redirect or a visible login form."""
    lowered = url.lower()
    if any(marker in lowered for marker in ("/login", "sso", "auth", "passport")):
        return True
    try:
        return page.locator("input[type='password']").count() > 0
    except Exception:
        return False
