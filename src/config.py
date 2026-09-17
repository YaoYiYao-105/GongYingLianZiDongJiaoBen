"""Configuration and selector resolution.

All element locators live here rather than inside the workflow modules. When
the portal front-end is updated, this file (or the JSON file it loads) is the
only thing that needs to change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .paths import config_dir

DEFAULT_BASE_URL = "https://glzx.yonghui.cn/supplier-rMicro/upiCenter/upiMaintain"

SELECTOR_FILE_NAME = "selectors.json"

#: Selector expression kinds understood by :func:`parse_locator_expression`.
SUPPORTED_KINDS = frozenset({"css", "text", "placeholder", "label", "role"})

#: Keywords allowed inside role expressions, e.g. ``role=button[name='查询']``.
ROLE_KEYWORDS = frozenset({"name", "exact"})


@dataclass
class Target:
    """A logical page element, described by an ordered list of locators.

    Candidates are tried in order; the first one that resolves wins. Listing
    several candidates keeps the script working when markup shifts slightly.
    """

    name: str
    candidates: list[str] = field(default_factory=list)
    description: str = ""


def _default_selectors() -> dict[str, Any]:
    # NOTE: these candidates are educated guesses. Run `python main.py calibrate`
    # against the real portal and then tighten them.
    return {
        "version": 1,
        "base_url": DEFAULT_BASE_URL,
        "steps": {
            "upi_query": {
                "date_input": [
                    "css=input[placeholder*='日期']",
                    "css=.el-date-editor input",
                    "placeholder=请选择日期",
                ],
                "query_button": [
                    "role=button[name='查询']",
                    "role=button[name='搜索']",
                    "text=查询",
                ],
                "order_links": [
                    "css=a[href*='order']",
                    "css=td a",
                ],
            },
            "order_flow": {
                "order_entry": [
                    "css=td",
                ],
                "approval_link": [
                    "role=link[name='订货审批单']",
                    "text=订货审批单",
                ],
            },
            "box_code": {
                "rows": [
                    "css=.el-table__body tbody tr",
                    "css=table tbody tr",
                ],
                "date_cell": [
                    "css=td:nth-child(2)",
                    "css=td",
                ],
                "box_input": [
                    "css=input",
                ],
                "save_button": [
                    "role=button[name='保存']",
                    "text=保存",
                ],
            },
        },
        "behavior": {
            "minimize_window": True,
        },
        "timing": {
            "action_delay_ms": 450,
            "action_jitter_ms": 350,
            "nav_timeout_ms": 30000,
        },
    }


def load_config() -> dict[str, Any]:
    """Load the selector file, materialising defaults on first run."""
    path = config_dir() / SELECTOR_FILE_NAME
    if not path.exists():
        ensure_config_dir()
        path.write_text(
            json.dumps(_default_selectors(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return _default_selectors()
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_config_dir() -> None:
    config_dir().mkdir(parents=True, exist_ok=True)


def parse_locator_expression(expression: str) -> Callable[[Any], Any]:
    """Turn a short selector expression into a Playwright locator factory.

    Supported forms::

        css=<css selector>
        text=<visible text>
        role=button[name='查询']
        placeholder=<input placeholder>
        label=<form label>

    The expression is validated eagerly so a typo in the configuration file is
    reported when it is loaded, not hours later in the middle of a run.
    """

    if "=" not in expression:
        raise ValueError(f"selector expression needs a 'kind=value' form: {expression!r}")

    kind, _, value = expression.partition("=")
    kind = kind.strip().lower()
    value = value.strip()

    if kind not in SUPPORTED_KINDS:
        raise ValueError(f"unsupported selector kind: {kind!r} in {expression!r}")

    role_name = ""
    role_kwargs: dict[str, str] = {}
    if kind == "role":
        role_name, _, rest = value.partition("[")
        role_name = role_name.strip()
        if rest.endswith("]"):
            for pair in rest[:-1].split(","):
                key, _, val = pair.partition("=")
                key = key.strip()
                if key not in ROLE_KEYWORDS:
                    raise ValueError(
                        f"unsupported role keyword {key!r} in {expression!r}; "
                        f"expected one of {sorted(ROLE_KEYWORDS)}"
                    )
                role_kwargs[key] = val.strip().strip("'\"")

    def build(scope: Any) -> Any:
        if kind == "css":
            return scope.locator(value)
        if kind == "text":
            return scope.get_by_text(value, exact=False)
        if kind == "placeholder":
            return scope.get_by_placeholder(value)
        if kind == "label":
            return scope.get_by_label(value)
        return scope.get_by_role(role_name, **role_kwargs)

    return build


def resolve(scope: Any, candidates: list[str], timeout_ms: int = 5000) -> Any | None:
    """Return the first candidate that resolves to a *single visible* element."""
    for expression in candidates:
        try:
            locator = parse_locator_expression(expression)(scope).first
            if locator.count() and locator.is_visible(timeout=timeout_ms):
                return locator
        except Exception:
            continue
    return None


def resolve_all(scope: Any, candidates: list[str], timeout_ms: int = 5000) -> Any | None:
    """Return the first candidate that matches *one or more* elements.

    Collections such as table rows must not be narrowed with ``.first``,
    otherwise only the first row is ever processed.
    """
    for expression in candidates:
        try:
            locator = parse_locator_expression(expression)(scope)
            if locator.count():
                return locator
        except Exception:
            continue
    return None
