"""Translate raw exceptions into something an operator can act on.

A colleague who double-clicks the packaged application should never be shown a
Playwright or asyncio traceback. Those still get written to the run log for
diagnosis; what is printed and displayed is the plain sentence produced here.

Messages are Chinese because the people reading them are Chinese-speaking
operators. Developer-facing log lines stay English.
"""

from __future__ import annotations

#: Chromium network error codes mapped to a cause and an action.
_NETWORK_ERRORS = {
    "ERR_UNSAFE_PORT": "无法连接后台地址（端口被浏览器拦下），请检查配置里的地址是否正确。",
    "ERR_CONNECTION_REFUSED": "后台拒绝了连接，地址或端口可能不正确。",
    "ERR_CONNECTION_RESET": "连接被中断，网络可能不稳定，建议重试。",
    "ERR_CONNECTION_TIMED_OUT": "连接后台超时，请检查网络是否可以访问该地址。",
    "ERR_NAME_NOT_RESOLVED": "无法解析后台域名，请检查网络或 DNS 设置。",
    "ERR_INTERNET_DISCONNECTED": "本机没有网络连接。",
    "ERR_EMPTY_RESPONSE": "后台没有返回数据，连接可能被中途切断，建议重试。",
    "ERR_SSL_PROTOCOL_ERROR": "与后台的加密连接失败，可能被网络中间设备拦截。",
}

#: Raised when the stored profile no longer carries a valid session.
NOT_LOGGED_IN_MESSAGE = "未登录。请先点「登录」完成一次登录（首次需要短信验证）。"

#: Raised when the workflow is stopped from the keyboard.
INTERRUPTED_MESSAGE = "已被手动中断，已完成的进度已经保存。"


def explain(exc: BaseException) -> str:
    """Return one actionable sentence describing ``exc``."""
    text = str(exc)

    for code, message in _NETWORK_ERRORS.items():
        if code in text:
            return message

    lowered = text.lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "等待页面响应超时，后台可能响应很慢或网络不通。"
    if "no usable browser" in lowered:
        return "找不到可用的浏览器，请先安装 Microsoft Edge 或 Google Chrome。"
    if "not found" in lowered or "tighten" in lowered:
        return "页面上找不到预期的元素，前端可能已经改版，请重新运行「标定」更新定位配置。"
    if "target closed" in lowered or "browser has been closed" in lowered:
        return "浏览器窗口被关闭了，运行已中断。"

    first_line = next((line for line in text.splitlines() if line.strip()), "")
    return first_line[:200] if first_line else exc.__class__.__name__
