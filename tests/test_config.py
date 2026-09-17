import pytest

from src.config import parse_locator_expression


class RecordingPage:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def locator(self, value):
        self.calls.append(("locator", value))
        return "locator"

    def get_by_text(self, value, exact=False):
        self.calls.append(("get_by_text", value, exact))
        return "text"

    def get_by_placeholder(self, value):
        self.calls.append(("get_by_placeholder", value))
        return "placeholder"

    def get_by_label(self, value):
        self.calls.append(("get_by_label", value))
        return "label"

    def get_by_role(self, role, **kwargs):
        self.calls.append(("get_by_role", role, kwargs))
        return "role"


def test_parses_css_expression():
    page = RecordingPage()
    assert parse_locator_expression("css=table tbody tr")(page) == "locator"
    assert page.calls == [("locator", "table tbody tr")]


def test_parses_text_expression():
    page = RecordingPage()
    parse_locator_expression("text=订货审批单")(page)
    assert page.calls == [("get_by_text", "订货审批单", False)]


def test_parses_role_expression_with_name():
    page = RecordingPage()
    parse_locator_expression("role=button[name='查询']")(page)
    assert page.calls == [("get_by_role", "button", {"name": "查询"})]


def test_parses_role_expression_without_arguments():
    page = RecordingPage()
    parse_locator_expression("role=button")(page)
    assert page.calls == [("get_by_role", "button", {})]


def test_rejects_expression_without_kind():
    with pytest.raises(ValueError, match="kind=value"):
        parse_locator_expression("table tbody tr")


def test_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unsupported selector kind"):
        parse_locator_expression("xpath=//table")


class CountingPage:
    """A page whose locator always matches a fixed number of elements."""

    def __init__(self, matches: int) -> None:
        self.matches = matches
        self.queries: list[str] = []

    def locator(self, value):
        self.queries.append(value)
        outer = self

        class Matching:
            def __init__(self) -> None:
                pass

            @property
            def first(self):
                return Matching()

            def count(self):
                return outer.matches

            def is_visible(self, timeout=None):
                return outer.matches > 0

        return Matching()


def test_resolve_returns_first_matching_candidate():
    from src.config import resolve

    page = CountingPage(1)
    assert resolve(page, ["css=tbody tr"]) is not None
    assert page.queries == ["tbody tr"]


def test_resolve_gives_up_when_nothing_matches():
    from src.config import resolve

    page = CountingPage(0)
    assert resolve(page, ["css=tbody tr", "css=table tr"]) is None
    assert page.queries == ["tbody tr", "table tr"], "candidates are tried in order"


def test_resolve_all_keeps_every_match():
    """Regression: table row collections must not be narrowed to the first row."""
    from src.config import resolve_all

    page = CountingPage(7)
    locator = resolve_all(page, ["css=tbody tr"])
    assert locator.count() == 7, "only the first row was returned"
