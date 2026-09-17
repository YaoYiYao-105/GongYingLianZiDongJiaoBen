# Architecture

## The problem

A supplier portal requires, every single day, the same sequence of clicks:

1. pick today's date on a maintenance page and search
2. open each dispatched order's detail page
3. open its approval form
4. click the order date on every product row and type a box code of `1`

The whole thing takes five or six minutes. It is not slow — it is *tedious*,
which is exactly the kind of work software should absorb.

## Why not drive the underlying APIs directly?

Replaying the portal's XHR calls would be far faster: thousands of clicks
collapse into a handful of HTTP requests. It was deliberately rejected.

- The total work is ~5 minutes. Compressing it to 30 seconds does not pay for
  the reverse-engineering effort.
- The real cost of API replay is long-term: request signing, rotating tokens
  and undocumented payloads break silently and break *badly* — a malformed
  write can corrupt production data rather than simply failing a locator.
- A visible browser performing the same steps a human would is also far less
  likely to trip anti-automation defences.

The chosen approach is the smallest thing that works: automate the clicks.

## Layering

The single most important structural decision is that **element locators never
appear in business logic**. Workflow modules describe *what* to do; one file
describes *where* to do it.

```
                    ┌──────────────────────────────┐
                    │  main.py    (CLI)             │
                    │  src/gui.py (double-click app)│
                    └───────────────┬──────────────┘
                                    │
                    ┌───────────────▼──────────────┐
                    │  src/workflow.py             │
                    │  orchestration + reporting   │
                    └───┬──────────┬──────────┬────┘
                        │          │          │
        ┌───────────────▼──┐  ┌────▼───────┐  ┌▼──────────────┐
        │ steps/upi_query  │  │ steps/     │  │ steps/        │
        │ date+search+list │  │ order_flow │  │ box_code      │
        └──────────────────┘  └────────────┘  └───────────────┘
                        │          │          │
                        └──────────┴──────┬───┘
                                          ▼
                              ┌───────────────────────┐
                              │ src/config.py         │
                              │ the only locator home │
                              └───────────────────────┘

  src/browser.py   persistent profile, channel detection, window state
  src/state.py     JSONL journal for resuming interrupted runs
  src/report.py    per-run folders, screenshots, summary
  src/calibrate.py one-off capture of the real page structure
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
- **Idempotent.** A row already holding `1` is skipped, so re-running after an
  interruption cannot double-submit.
- **Fail visibly, not creatively.** If a locator cannot be found the row is
  marked failed and the run moves on. Nothing is clicked "just in case".
- **Partial failure never submits.** The save button is only pressed when every
  row in the table succeeded.
- **Resumable.** Completed orders are journalled, so an interrupted run picks
  up where it stopped.

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
