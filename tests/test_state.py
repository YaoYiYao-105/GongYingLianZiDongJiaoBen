import pytest

from src import state


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(state, "ensure_dirs", lambda: None)
    return tmp_path


def test_missing_journal_reports_nothing_completed(journal):
    assert state.load_completed() == set()


def test_only_successful_orders_count_as_completed(journal):
    state.append({"order_no": "A1", "status": "succeeded"})
    state.append({"order_no": "A2", "status": "failed"})
    state.append({"order_no": "A3", "status": "skipped"})
    assert state.load_completed() == {"A1"}


def test_appends_rather_than_overwrites(journal):
    state.append({"order_no": "A1", "status": "succeeded"})
    state.append({"order_no": "A2", "status": "succeeded"})
    assert state.load_completed() == {"A1", "A2"}
    assert len((journal / f"{__import__('datetime').date.today():%Y-%m-%d}.jsonl").read_text().splitlines()) == 2
