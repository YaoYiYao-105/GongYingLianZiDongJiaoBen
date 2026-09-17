from src.steps.box_code import fill_rows

SELECTORS = {
    "rows": ["css=table tbody tr"],
    "date_cell": ["css=td"],
    "box_input": ["css=input"],
    "save_button": ["role=button[name='保存']"],
}


def _run(page, commit, logs=None):
    collected = logs if logs is not None else []
    return fill_rows(
        page,
        SELECTORS,
        commit=commit,
        log=collected.append,
        pause=lambda: None,
    )


def test_dry_run_counts_every_row_without_writing(fake_page, fake_row):
    rows = [fake_row("") for _ in range(3)]
    stats = _run(fake_page(rows), commit=False)
    assert (stats.filled, stats.skipped, stats.failed) == (3, 0, 0)
    assert all(row.box_input.writes == [] for row in rows)


def test_commit_writes_box_code_one_to_every_row(fake_page, fake_row):
    rows = [fake_row("") for _ in range(2)]
    stats = _run(fake_page(rows), commit=True)
    assert stats.filled == 2
    assert [row.box_input.value for row in rows] == ["1", "1"]


def test_rows_already_set_to_one_are_skipped(fake_page, fake_row):
    rows = [fake_row("1"), fake_row("")]
    stats = _run(fake_page(rows), commit=True)
    assert (stats.filled, stats.skipped) == (1, 1)
    assert rows[0].box_input.writes == []


def test_row_without_input_is_reported_as_failed(fake_page, fake_row):
    rows = [fake_row("", has_input=False), fake_row("")]
    stats = _run(fake_page(rows), commit=True)
    assert (stats.filled, stats.failed) == (1, 1)


def test_order_date_is_clicked_before_the_box_code_is_typed(fake_page, fake_row):
    row = fake_row("")
    _run(fake_page([row]), commit=True)
    assert row.date_cell.clicks == 1


def test_save_button_clicked_only_after_a_clean_commit(fake_page, fake_row, fake_element):
    button = fake_element()
    _run(fake_page([fake_row("")], save_button=button), commit=True)
    assert button.clicks == 1

    button.clicks = 0
    _run(fake_page([fake_row("", has_input=False)], save_button=button), commit=True)
    assert button.clicks == 0, "a partially failed table must not be submitted"

    button.clicks = 0
    _run(fake_page([fake_row("")], save_button=button), commit=False)
    assert button.clicks == 0, "dry runs must never submit"
