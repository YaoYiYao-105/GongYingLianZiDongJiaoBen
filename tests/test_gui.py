"""Tests for the completion notification.

The tool is meant to be started and walked away from, so "did the operator get
told" is real behaviour worth pinning down rather than trusting by eye.
"""

from __future__ import annotations

import pytest

from src import gui


@pytest.fixture
def app(monkeypatch):
    try:
        instance = gui.AutomationApp()
    except Exception as exc:  # no display available
        pytest.skip(f"tkinter cannot open a window here: {exc}")

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
