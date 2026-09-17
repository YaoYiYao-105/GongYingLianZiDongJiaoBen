"""Lightweight stand-ins for the Playwright objects used by the workflow.

The selector and row-walking logic is pure bookkeeping, so it can be verified
without launching a browser.
"""

from __future__ import annotations

import pytest


class FakeElement:
    def __init__(self, value: str = "", visible: bool = True) -> None:
        self.value = value
        self.visible = visible
        self.writes: list[str] = []
        self.clicks = 0

    def input_value(self) -> str:
        return self.value

    def fill(self, value: str) -> None:
        self.value = value
        self.writes.append(value)

    def click(self) -> None:
        self.clicks += 1

    def inner_text(self) -> str:
        return self.value

    def is_visible(self, timeout: int | None = None) -> bool:
        return self.visible


class FakeRow:
    """One box-code table row: a date cell plus a box-code input."""

    def __init__(self, box_value: str = "", has_input: bool = True) -> None:
        self.date_cell = FakeElement("2026-09-17")
        self.box_input = FakeElement(box_value)
        self._has_input = has_input
        self.clicks = 0

    def click(self) -> None:
        self.clicks += 1

    def locator(self, selector: str):
        if "input" in selector:
            return FakeLocator([self.box_input] if self._has_input else [])
        return FakeLocator([self.date_cell])


class FakeLocator:
    def __init__(self, elements: list) -> None:
        self._elements = elements

    @property
    def first(self) -> "FakeLocator":
        return FakeLocator(self._elements[:1])

    def count(self) -> int:
        return len(self._elements)

    def nth(self, index: int) -> "FakeLocator":
        return FakeLocator([self._elements[index]])

    def is_visible(self, timeout: int | None = None) -> bool:
        return bool(self._elements) and getattr(self._elements[0], "visible", True)

    def input_value(self) -> str:
        return self._elements[0].input_value()

    def inner_text(self) -> str:
        return self._elements[0].inner_text()

    def fill(self, value: str) -> None:
        self._elements[0].fill(value)

    def click(self) -> None:
        self._elements[0].click()

    def locator(self, selector: str):
        return self._elements[0].locator(selector)


class FakePage:
    def __init__(self, rows: list[FakeRow] | None = None, save_button: FakeElement | None = None) -> None:
        self.rows = rows or []
        self.save_button = save_button

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(list(self.rows))

    def get_by_role(self, role: str, **kwargs) -> FakeLocator:
        if self.save_button is not None:
            return FakeLocator([self.save_button])
        return FakeLocator([])

    def get_by_text(self, text: str, exact: bool = False) -> FakeLocator:
        return FakeLocator([])

    def get_by_placeholder(self, text: str) -> FakeLocator:
        return FakeLocator([])

    def get_by_label(self, text: str) -> FakeLocator:
        return FakeLocator([])

    def wait_for_load_state(self, state: str = "load", timeout: int | None = None) -> None:
        return None


@pytest.fixture
def fake_page():
    return FakePage


@pytest.fixture
def fake_row():
    return FakeRow


@pytest.fixture
def fake_element():
    return FakeElement
