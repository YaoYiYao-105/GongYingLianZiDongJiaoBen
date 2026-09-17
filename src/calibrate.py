"""One-off calibration pass.

The script ships with *guessed* locators. Running calibration against the real
portal produces an inventory of the actual inputs, buttons and table layout,
which is then used to tighten the selector configuration.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import browser as browser_module
from .config import load_config
from .paths import ensure_dirs, runs_dir
from .report import RunContext

INVENTORY_SCRIPT = """
() => {
  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim().slice(0, 120);
  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute('type') || '',
    placeholder: clean(el.getAttribute('placeholder')),
    name: el.getAttribute('name') || '',
    id: el.id || '',
    className: clean(String(el.className || '')).slice(0, 160),
    text: clean(el.innerText || el.value || ''),
    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
  });
  const inputs = [...document.querySelectorAll('input, textarea, select')].map(describe);
  const clickable = [...document.querySelectorAll('button, a, [role=button]')].map(describe);
  const tables = [...document.querySelectorAll('table')].map((t) => ({
    headers: [...t.querySelectorAll('thead th')].map((th) => clean(th.innerText)),
    firstRow: [...(t.querySelector('tbody tr')?.querySelectorAll('td') || [])].map((td) => clean(td.innerText)),
    rowCount: t.querySelectorAll('tbody tr').length,
  }));
  return { url: location.href, title: document.title, inputs, clickable, tables };
}
"""


def _render_markdown(inventory: dict) -> str:
    lines = [
        "# Page inventory",
        "",
        f"- URL: `{inventory.get('url', '')}`",
        f"- Title: {inventory.get('title', '')}",
        "",
        "## Inputs",
        "",
        "| tag | type | placeholder | name | id | class | visible |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in inventory.get("inputs", []):
        lines.append(
            "| {tag} | {type} | {placeholder} | {name} | {id} | {className} | {visible} |".format(**item)
        )

    lines += ["", "## Buttons and links", "", "| tag | text | class | visible |", "| --- | --- | --- | --- |"]
    for item in inventory.get("clickable", []):
        lines.append("| {tag} | {text} | {className} | {visible} |".format(**item))

    lines += ["", "## Tables", ""]
    for index, table in enumerate(inventory.get("tables", [])):
        lines.append(f"### Table {index + 1} — {table.get('rowCount', 0)} rows")
        lines.append("")
        lines.append("- headers: " + " | ".join(table.get("headers", [])))
        lines.append("- first row: " + " | ".join(table.get("firstRow", [])))
        lines.append("")

    return "\n".join(lines)


def capture(page, context: RunContext, label: str) -> Path:
    inventory = page.evaluate(INVENTORY_SCRIPT)
    context.dump_html(page, label)
    context.screenshot(page, label)

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    directory = runs_dir() / f"calibrate-{stamp}"
    directory.mkdir(parents=True, exist_ok=True)

    (directory / f"{label}.json").write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    markdown = _render_markdown(inventory)
    (directory / f"{label}.md").write_text(markdown, encoding="utf-8")
    context.log(f"calibration saved to {directory}")
    return directory


def run(notify: Callable[[str], None] = input) -> None:
    ensure_dirs()
    config = load_config()
    context = RunContext()
    session = browser_module.launch(headless=False)

    try:
        page = session.page
        context.log("opening portal ...")
        page.goto(config["base_url"], wait_until="domcontentloaded", timeout=60000)

        if browser_module.looks_logged_out(page.url, page):
            context.log("=" * 64)
            context.log("NOT LOGGED IN — please sign in inside the browser window.")
            context.log("SMS verification is required the first time on a new device.")
            context.log("=" * 64)
            notify("press Enter once you are logged in and can see the portal ... ")
        else:
            context.log("existing login session detected")

        context.log("-" * 64)
        context.log("Now walk the manual path and STOP on the box-code page:")
        context.log("  1. pick today's date on the UPI maintenance page and search")
        context.log("  2. open one order's detail, then open its approval form")
        context.log("  3. stop when the box-code table is on screen")
        context.log("-" * 64)
        notify("press Enter when the box-code page is visible ... ")

        directory = capture(page, context, "boxcode-page")
        context.log("")
        context.log("Send the generated files (or just the .md) back for selector tuning:")
        context.log(f"  {directory}")
    finally:
        notify("press Enter to close the browser ... ")
        session.close()
