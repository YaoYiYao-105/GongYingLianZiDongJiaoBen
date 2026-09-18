"""Tests for the completion notification.

The tool is meant to be started and walked away from, so "did the operator get
told" is real behaviour worth pinning down rather than trusting by eye.
"""

from __future__ import annotations

import os
import sys
import time
import tkinter

import pytest

from src import gui


def _open_window(attempts: int = 3):
    """Open a Tk root, tolerating the transient failures Windows CI shows.

    Destroying one Tk root and immediately creating the next occasionally fails
    on Windows, so a short back-off is enough to let the previous one go.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return gui.AutomationApp()
        except tkinter.TclError as exc:
            last = exc
            time.sleep(0.25 * (attempt + 1))
    raise last


def _display_is_expected() -> bool:
    """False only on a genuinely headless Linux box."""
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


@pytest.fixture
def app(monkeypatch):
    try:
        instance = _open_window()
    except Exception as exc:
        if not _display_is_expected():
            pytest.skip(f"tkinter cannot open a window here: {exc}")
        # A display is expected, so nothing is hidden here: quietly skipping
        # would mask GUI breakage on the very platforms the operators use.
        pytest.fail(f"tkinter could not open a window: {exc}")

    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        gui.messagebox, "showinfo", lambda title, message, **kw: shown.append(("info", message))
    )
    monkeypatch.setattr(
        gui.messagebox, "showwarning", lambda title, message, **kw: shown.append(("warning", message))
    )
    instance._dialogs = shown
    try:
        yield instance
    finally:
        instance.destroy()


def test_a_successful_run_is_announced(app):
    app._finish(gui.Outcome(ok=True, headline="全部完成", detail="订单 3，填写 12 行"))

    assert app._dialogs, "the operator was never told the run finished"
    assert app._dialogs[0][0] == "info"
    assert "12" in app._dialogs[0][1]


def test_a_failed_run_is_announced_differently_from_a_successful_one(app):
    app._finish(gui.Outcome(ok=False, headline="有 1 个订单处理失败", detail="详见日志目录"))

    assert app._dialogs
    assert app._dialogs[0][0] == "warning"


def test_the_window_title_reflects_the_outcome(app):
    """The taskbar entry is the only cue when the window is behind others."""
    app._finish(gui.Outcome(ok=True, headline="全部完成"))
    assert "完成" in app.title()

    app._finish(gui.Outcome(ok=False, headline="运行中止 — 无法连接后台地址"))
    assert "有失败项" in app.title()


def test_an_abort_reason_reaches_the_operator(app):
    app._finish(gui.Outcome(ok=False, headline="运行中止 — 无法连接后台地址，请检查网络。"))

    assert "无法连接后台地址" in app._dialogs[0][1]


def test_buttons_are_usable_again_after_a_run(app):
    app._set_busy(True)
    app._finish(gui.Outcome(ok=True, headline="全部完成"))

    assert str(app._commit_button["state"]) == "normal"
    assert app._is_busy() is False


def test_finishing_never_steals_focus(app, monkeypatch):
    """The run is meant to be walked away from; it must not grab the screen.

    Only the closing dialog is allowed to interrupt, and it is a dialog the
    operator already expects. Raising the window, restoring it from the
    taskbar or forcing focus would yank someone out of whatever they moved on
    to, so those calls are banned outright.
    """

    def banned(name):
        def explode(*_args, **_kwargs):
            pytest.fail(f"{name}() was called while finishing a run")

        return explode

    for name in ("deiconify", "lift", "focus_force"):
        monkeypatch.setattr(gui.AutomationApp, name, banned(name))

    app._finish(gui.Outcome(ok=True, headline="全部完成", detail="订单 3，填写 12 行"))

    assert app._dialogs, "the closing dialog is the one interruption allowed"


def test_the_closing_dialog_is_on_top_but_the_window_does_not_stay_there(app, monkeypatch):
    """The result has to be visible, yet the app must not camp above other work."""
    seen: list[bool] = []

    def pinned() -> bool:
        return str(app.attributes("-topmost")).strip().lower() in {"1", "true"}

    monkeypatch.setattr(
        gui.messagebox,
        "showinfo",
        lambda title, message, **kw: seen.append(pinned()),
    )

    app._finish(gui.Outcome(ok=True, headline="全部完成"))

    assert seen == [True], "the dialog was not pinned, so a maximised window would hide it"
    assert not pinned(), "the window stayed on top after the dialog closed"


def test_a_question_the_operator_cannot_see_still_gets_answered(app):
    """Login asks the operator to go and sign in; that dialog must be reachable.

    It also blocks the worker until dismissed, so one hidden behind the browser
    window would look like a hang rather than a question.
    """
    app._messages.put(("prompt", "请在浏览器窗口中完成登录，完成后点「确定」。"))
    app._drain_messages()

    assert app._dialogs and "完成登录" in app._dialogs[0][1]


# ------------------------------------------------------------- session caching
def test_a_successful_login_caches_the_session(app, monkeypatch):
    """Otherwise every maintenance run would have to open a browser again."""
    stored: list = []
    monkeypatch.setattr(gui.api_workflow, "read_credentials", lambda page: "creds")
    monkeypatch.setattr(gui.api_workflow, "store", lambda credentials: stored.append(credentials))

    app._remember_session(object())

    assert stored == ["creds"]
    assert "缓存" in app._messages.get_nowait()[1]


def test_a_failed_capture_still_reports_a_successful_login(app, monkeypatch):
    """The page may need a moment longer to write its storage; that is not a
    login failure, and the run path reads it again anyway."""
    def explode(page):
        raise RuntimeError("nothing in storage yet")

    monkeypatch.setattr(gui.api_workflow, "read_credentials", explode)

    app._remember_session(object())  # must not raise

    assert "暂未缓存" in app._messages.get_nowait()[1]
