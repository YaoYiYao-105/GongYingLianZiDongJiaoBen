# Architecture

## The problem

A supplier portal requires, every single day, the same sequence of clicks:

1. pick today's date on a maintenance page and search
2. open each dispatched order's detail page
3. open its approval form
4. click the order date on every product row and type a box code of `1`

The whole thing takes five or six minutes. It is not slow — it is *tedious*,
which is exactly the kind of work software should absorb.

## Two drivers, and why the second one exists

The first version clicked, and only clicked. Replaying the portal's own requests
was rejected up front as poor value for money: the job takes five minutes, the
signing scheme was unknown, and an undocumented payload that writes *badly*
corrupts production data in a way a failed locator never will.

That reasoning was sound but the estimate behind it was wrong. The signing
scheme turned out to be short and entirely derivable from what the page already
does, so the reverse engineering was an afternoon rather than a project. The
driver in `src/api.py` now replays those requests directly.

What made the change safe enough to make — and this is the part that matters —
was not the speed:

- **Only orders the portal itself calls unfinished are touched.** The server
  enforces the same rule, so a write against a stale order is refused rather
  than applied.
- **Every save is read back.** A success code proves the request was accepted,
  not that the rows landed. The driver re-fetches the order and checks each row
  individually; mismatches are failures, not assumptions.
- **Dry run is still the default**, in both drivers.

The click driver stays in `src/workflow.py` (`run_browser`) as a fallback. It
is the slower, more visible path, and it is the one that keeps working if the
endpoints are ever withdrawn.

## Layering

The single most important structural decision is that **element locators never
appear in business logic**. Workflow modules describe *what* to do; one file
describes *where* to do it.

```
                    ┌──────────────────────────────┐
                    │  main.py    (CLI)             │
                    │  src/gui.py (double-click app)│
                    └───────────────┬──────────────┘
                                    │  mode = api | browser
                    ┌───────────────▼──────────────┐
                    │  src/workflow.py             │
                    │  picks a driver              │
                    └───┬──────────────────────┬───┘
                        │                      │
        ┌───────────────▼──────────┐  ┌────────▼─────────────────┐
        │  src/api_workflow.py     │  │  steps/upi_query         │
        │  query → read → save →   │  │  steps/order_flow        │
        │  read back and verify    │  │  steps/box_code          │
        │      └── src/api.py      │  │        │                 │
        │          signing+bodies  │  │        ▼                 │
        └──────────────────────────┘  │  src/config.py           │
                                      │  the only locator home   │
                                      └──────────────────────────┘

  src/browser.py    persistent profile, channel detection, window state
  src/state.py      JSONL journal for resuming interrupted runs
  src/report.py     per-run folders, screenshots, summary
  src/calibrate.py  one-off capture of the real page structure
```

## Selector expressions

Locators are stored as short, readable strings so that non-programmers can
adjust them without touching Python:

| Expression | Resolves to |
| --- | --- |
| `css=table tbody tr` | CSS selector |
| `text=订货审批单` | visible text |
| `role=button[name='查询']` | accessibility role plus name |
| `placeholder=请选择日期` | input placeholder |
| `label=箱码` | form label |

Each logical target holds an **ordered list** of expressions. The first one
that resolves wins, so minor markup changes do not break the run.

Two resolution helpers exist, and the distinction matters:

- `resolve()` narrows to a single visible element — used for buttons and fields.
- `resolve_all()` keeps every match — used for table rows. Narrowing a row
  collection with `.first` silently processes only the first product, which is
  the kind of bug that looks like success. There is a regression test for it.

## The calibration loop

The shipped locators are educated guesses, so the first run against a real
portal is a calibration pass:

```
python main.py calibrate
```

It opens the portal, waits while the operator signs in and navigates to the
box-code page, then captures the DOM, an element inventory and a screenshot.
The inventory is what turns guessed selectors into exact ones. Calibration
performs no typing and no submission.

## Safety model

Writing to a production back office is the risky part, so the defaults are
deliberately biased toward doing nothing:

- **Dry run by default.** `run` inspects and reports; only `--commit` writes.
- **Idempotent.** The click driver skips rows already holding `1`. The API
  driver only touches orders the portal still reports as unexecuted, and a
  written order stops being one — so a re-run cannot double-submit either way.
- **Fail visibly, not creatively.** If a locator cannot be found the row is
  marked failed and the run moves on. Nothing is clicked "just in case".
- **Partial failure never submits.** The click driver only presses save when
  every row succeeded. The API driver sends one body per order, which the server
  applies as a unit, and then re-reads the order and checks every row against
  what it meant to write.
- **Resumable.** Completed orders are journalled, so an interrupted run picks up
  where it stopped. Dry runs are deliberately *not* journalled: recording them
  would make the next real run skip work that was never done.

## Sessions

The endpoints need the same session the browser holds, and that session lives in
the browser profile. `src/api_workflow.py` therefore reads it once, caches it
next to the other run data, and reuses it until the server rejects it — at which
point it opens the profile, reads it again, and carries on. The common run
touches no browser at all.

Two properties make this acceptable rather than sloppy:

- The cache holds nothing the profile does not already hold, is written `0600`,
  and lives outside the repository like every other artifact.
- The API calls are plain HTTPS and carry no cookies, so the cached values are
  the whole of what crosses the wire.

## Browser handling

The portal treats each new device as untrusted and demands SMS verification.
That makes the profile directory load-bearing: it is persistent, lives outside
the repository, and is never deleted by the app.

The app drives a real branded browser rather than a bundled Chromium, trying
Microsoft Edge first (it ships with Windows), then Google Chrome, then falling
back to Playwright's Chromium. A branded build looks like an ordinary browser
session, and reusing an installed browser also keeps the package small.

The window can be minimised while work continues, which is safe because
Playwright already launches Chromium with background timer throttling,
renderer backgrounding and occluded-window throttling disabled. Without those
flags a minimised page stops rendering and automation stalls — a common cause
of "it hangs when I switch away".

## Distribution

A PyInstaller build produces a folder the operator unzips and double-clicks;
Python is not required on their machine. PyInstaller cannot cross-compile, so
Windows builds are produced by the GitHub Actions workflow or by
`scripts/build_windows.bat` on a Windows machine.

Because the front-end can change at any time, locator updates ship as a small
JSON file rather than a rebuilt executable. That was chosen over a remote
config service: it needs no infrastructure and covers the realistic case.
