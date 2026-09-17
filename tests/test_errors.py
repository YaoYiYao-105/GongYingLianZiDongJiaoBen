import pytest

from src.errors import explain


@pytest.mark.parametrize(
    "raw, expected_fragment",
    [
        ("Page.goto: net::ERR_UNSAFE_PORT at http://127.0.0.1:9/x", "无法连接后台地址"),
        ("net::ERR_CONNECTION_REFUSED", "拒绝了连接"),
        ("net::ERR_NAME_NOT_RESOLVED", "域名"),
        ("net::ERR_INTERNET_DISCONNECTED", "没有网络"),
        ("Timeout 30000ms exceeded", "超时"),
        ("query button not found — tighten steps.upi_query.query_button", "改版"),
        ("RuntimeError: no usable browser found:\n  msedge: x", "Edge"),
        ("Target closed", "浏览器窗口被关闭"),
    ],
)
def test_known_failures_are_explained_in_plain_language(raw, expected_fragment):
    assert expected_fragment in explain(RuntimeError(raw))


def test_an_unknown_failure_keeps_its_first_line():
    assert explain(RuntimeError("something odd\nsecond line")) == "something odd"


def test_a_message_less_exception_falls_back_to_its_class_name():
    assert explain(RuntimeError()) == "RuntimeError"


def test_an_absurdly_long_message_is_truncated():
    assert len(explain(RuntimeError("x" * 5000))) <= 200
