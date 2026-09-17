"""Tkinter front-end.

Colleagues double-click the packaged application, press one button, and the
browser work happens on its own. Tkinter is used deliberately: it ships with
Python, so the packaged executable stays around 60 MB instead of growing by
another 100 MB for a heavier toolkit.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk

from src import browser as browser_module
from src.config import load_config
from src.errors import explain
from src.paths import runs_dir

WINDOW_TITLE = "UPI 箱码维护助手"
POLL_INTERVAL_MS = 120


@dataclass
class Outcome:
    """What the operator is told once a run stops."""

    ok: bool
    headline: str
    detail: str = ""


class AutomationApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("780x540")
        self.minsize(660, 440)

        self._messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._prompt_answered = threading.Event()

        self._build_widgets()
        self.after(POLL_INTERVAL_MS, self._drain_messages)

    # ------------------------------------------------------------------ layout
    def _build_widgets(self) -> None:
        header = ttk.Frame(self, padding=(18, 16, 18, 4))
        header.pack(fill="x")
        ttk.Label(header, text=WINDOW_TITLE, font=("", 17, "bold")).pack(anchor="w")
        ttk.Label(
            header,
            text="首次使用请先点「登录」完成一次短信验证，之后每天点「开始维护」即可。",
            foreground="#555555",
        ).pack(anchor="w", pady=(6, 0))

        buttons = ttk.Frame(self, padding=(18, 10))
        buttons.pack(fill="x")
        self._login_button = ttk.Button(buttons, text="登录", command=self._on_login)
        self._login_button.pack(side="left")
        self._dry_button = ttk.Button(buttons, text="试运行", command=lambda: self._start(commit=False))
        self._dry_button.pack(side="left", padx=8)
        self._commit_button = ttk.Button(buttons, text="开始维护", command=lambda: self._start(commit=True))
        self._commit_button.pack(side="left")
        ttk.Button(buttons, text="打开日志目录", command=self._open_runs).pack(side="right")

        self._status = tk.StringVar(value="就绪")
        ttk.Label(self, textvariable=self._status, padding=(18, 0, 18, 8)).pack(fill="x")

        log_frame = ttk.Frame(self, padding=(18, 0, 18, 18))
        log_frame.pack(fill="both", expand=True)
        self._log = tk.Text(log_frame, wrap="word", state="disabled", height=18)
        scrollbar = ttk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=scrollbar.set)
        self._log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    # --------------------------------------------------------------- plumbing
    def _append(self, text: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _drain_messages(self) -> None:
        """Move worker-thread output onto the UI thread."""
        try:
            while True:
                kind, payload = self._messages.get_nowait()
                if kind == "log":
                    self._append(str(payload))
                elif kind == "status":
                    self._status.set(str(payload))
                elif kind == "prompt":
                    text = str(payload)
                    self._pinned(lambda: messagebox.showinfo(WINDOW_TITLE, text, parent=self))
                    self._prompt_answered.set()
                elif kind == "done":
                    self._finish(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.after(POLL_INTERVAL_MS, self._drain_messages)

    def _finish(self, outcome: Outcome) -> None:
        """Announce the result once, without interrupting earlier.

        Nothing happens while the run is in progress: no dialog, no window
        raised, no focus taken. The closing dialog is the single interruption,
        and it is deliberate — the whole point of the tool is that the operator
        presses one button and walks away.
        """
        self._append("")
        self._append(outcome.headline)
        if outcome.detail:
            self._append(outcome.detail)

        self._set_busy(False)
        self._status.set("完成" if outcome.ok else "需要处理")
        self.title(f"{WINDOW_TITLE} — {'完成' if outcome.ok else '有失败项'}")

        message = outcome.headline + (f"\n\n{outcome.detail}" if outcome.detail else "")
        self._notify(message, warning=not outcome.ok)

    def _notify(self, message: str, *, warning: bool) -> None:
        """Announce the outcome, on top of whatever else is on screen."""
        dialog = messagebox.showwarning if warning else messagebox.showinfo
        self._pinned(lambda: dialog(WINDOW_TITLE, message, parent=self))

    def _pinned(self, show) -> None:
        """Run a dialog with the window pinned for exactly as long as it is up.

        A notification buried behind a maximised window is not a notification,
        and a question nobody can see is worse: the worker stays blocked on it.
        The window is unpinned the moment the dialog closes, so it never
        lingers above the operator's other work.
        """
        try:
            self.attributes("-topmost", True)
        except tk.TclError:  # platform without the attribute — show it anyway
            pass
        try:
            show()
        finally:
            try:
                self.attributes("-topmost", False)
            except tk.TclError:
                pass

    def _prompt(self, message: str) -> None:
        """Block the worker until the operator dismisses a dialog."""
        self._messages.put(("prompt", message))
        self._prompt_answered.wait()
        self._prompt_answered.clear()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in (self._login_button, self._dry_button, self._commit_button):
            button.configure(state=state)

    def _open_runs(self) -> None:
        directory = runs_dir()
        directory.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(directory)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(directory)])
        else:
            subprocess.Popen(["xdg-open", str(directory)])

    # ----------------------------------------------------------------- actions
    def _on_login(self) -> None:
        if self._is_busy():
            return
        self._set_busy(True)
        self._status.set("等待登录 ...")
        self._worker = threading.Thread(target=self._login_worker, daemon=True)
        self._worker.start()

    def _login_worker(self) -> None:
        session = None
        try:
            session = browser_module.launch(headless=False)
            config = load_config()
            page = session.page
            page.goto(config["base_url"], wait_until="domcontentloaded", timeout=60000)

            if browser_module.looks_logged_out(page.url, page):
                self._messages.put(("log", "请在浏览器窗口中登录（首次使用需要短信验证）。"))
                self._prompt("请在打开的浏览器窗口中完成登录，登录成功后点「确定」。")
                self._messages.put(("log", "登录信息已保存到本机，之后无需重复验证。"))
                detail = "登录信息已保存在本机，之后无需重复验证。"
            else:
                self._messages.put(("log", "已检测到有效登录状态，无需重新登录。"))
                detail = "本机已存在有效登录状态。"
            self._messages.put(("done", Outcome(ok=True, headline="登录流程结束", detail=detail)))
        except Exception as exc:
            self._messages.put(("done", Outcome(ok=False, headline=f"登录失败 — {explain(exc)}")))
        finally:
            if session is not None:
                session.close()

    def _start(self, *, commit: bool) -> None:
        if self._is_busy():
            return
        if commit and not messagebox.askyesno(
            WINDOW_TITLE, "将向生产后台写入箱码数据，确定继续吗？\n\n建议先跑一次「试运行」确认清单。"
        ):
            return
        self._append("")
        self._append("=" * 60)
        self._set_busy(True)
        self._status.set("运行中 ...")
        self._worker = threading.Thread(target=self._run_worker, args=(commit,), daemon=True)
        self._worker.start()

    def _run_worker(self, commit: bool) -> None:
        try:
            from src.workflow import run as run_workflow

            report = run_workflow(commit=commit, log_sink=lambda line: self._messages.put(("log", line)))
            totals = report.totals()

            if report.aborted:
                self._messages.put(("done", Outcome(
                    ok=False,
                    headline=f"运行中止 — {report.abort_reason}",
                    detail="已完成的进度已经保存，再次运行会从中断处继续。",
                )))
                return

            summary = (
                "订单 {orders}，成功 {succeeded}，跳过 {skipped}，"
                "失败 {failed}，填写 {rows_filled} 行".format(**totals)
            )
            if totals["failed"]:
                self._messages.put(("done", Outcome(
                    ok=False,
                    headline=f"有 {totals['failed']} 个订单处理失败",
                    detail=summary + "\n\n请点「打开日志目录」查看失败截图。",
                )))
            else:
                self._messages.put(("done", Outcome(ok=True, headline="全部完成", detail=summary)))
        except Exception as exc:
            self._messages.put(("done", Outcome(ok=False, headline=f"运行出错 — {explain(exc)}")))

    def _is_busy(self) -> bool:
        return bool(self._worker and self._worker.is_alive())


def main() -> None:
    AutomationApp().mainloop()
