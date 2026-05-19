#!/usr/bin/env python3
"""Convert Software analyzer CSV reports into a single static HTML file.

Default use:
    cd Software
    python tools\\csv_reports_to_html.py

By default this finds the newest analyzer timestamp in reports/*.csv and writes
reports/csv_report_view_<timestamp>.html.
"""

from __future__ import annotations

import argparse
import csv
import html
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


TIMESTAMP_RE = re.compile(r"_(\d{8}_\d{6})\.csv$", re.IGNORECASE)


@dataclass
class CsvTable:
    path: Path
    title: str
    columns: list[str]
    rows: list[list[str]]
    error: str = ""


def software_root() -> Path:
    return Path(__file__).resolve().parents[1]


def timestamp_from_name(path: Path) -> str:
    match = TIMESTAMP_RE.search(path.name)
    return match.group(1) if match else ""


def latest_timestamp(reports_dir: Path) -> str:
    candidates = []
    for path in reports_dir.glob("*.csv"):
        stamp = timestamp_from_name(path)
        if stamp:
            candidates.append((path.stat().st_mtime, stamp))
    if not candidates:
        return ""
    candidates.sort()
    return candidates[-1][1]


def resolve_report_path(value: str, root: Path, reports_dir: Path) -> Path:
    path = Path(value)
    candidates = [
        path,
        root / path,
        reports_dir / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return path.resolve()


def pick_csv_files(
    reports_dir: Path,
    *,
    timestamp: str,
    include_all: bool,
    explicit_csvs: Iterable[str],
    root: Path,
) -> tuple[list[Path], str]:
    explicit = list(explicit_csvs)
    if explicit:
        paths = [resolve_report_path(item, root, reports_dir) for item in explicit]
        return sorted(paths, key=lambda path: path.name.lower()), "custom"

    if include_all:
        return sorted(reports_dir.glob("*.csv"), key=lambda path: path.name.lower()), "all"

    stamp = timestamp or latest_timestamp(reports_dir)
    if not stamp:
        return [], ""
    return sorted(reports_dir.glob(f"*_{stamp}.csv"), key=lambda path: path.name.lower()), stamp


def read_csv_table(path: Path) -> CsvTable:
    title = path.stem
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample)
            except csv.Error:
                dialect = csv.excel
            reader = csv.reader(handle, dialect)
            rows = list(reader)
    except Exception as exc:
        return CsvTable(path=path, title=title, columns=[], rows=[], error=str(exc))

    if not rows:
        return CsvTable(path=path, title=title, columns=[], rows=[])

    columns = [str(value) for value in rows[0]]
    data_rows = [[str(value) for value in row] for row in rows[1:]]
    return CsvTable(path=path, title=title, columns=columns, rows=data_rows)


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def shorten(value: str, max_cell_chars: int) -> str:
    if max_cell_chars <= 0 or len(value) <= max_cell_chars:
        return value
    return value[: max_cell_chars - 1] + "..."


def render_table(table: CsvTable, index: int, reports_dir: Path, max_cell_chars: int) -> str:
    table_id = f"table-{index}"
    try:
        rel = table.path.resolve().relative_to(reports_dir.resolve())
        csv_href = esc(rel.as_posix())
    except ValueError:
        csv_href = esc(table.path.as_posix())

    parts = [
        f'<details class="report" open>',
        f'<summary><span>{esc(table.title)}</span><small>{len(table.rows)} rows, {len(table.columns)} columns</small></summary>',
        '<div class="report-meta">',
        f'<a href="{csv_href}">Open CSV</a>',
        f'<code>{esc(str(table.path))}</code>',
        '</div>',
    ]

    if table.error:
        parts.append(f'<p class="error">Could not read CSV: {esc(table.error)}</p>')
        parts.append("</details>")
        return "\n".join(parts)

    if not table.columns:
        parts.append('<p class="empty">Empty CSV.</p>')
        parts.append("</details>")
        return "\n".join(parts)

    parts.extend(
        [
            '<div class="table-tools">',
            f'<input type="search" placeholder="Filter this table" data-target="{table_id}">',
            f'<button type="button" data-clear="{table_id}">Clear</button>',
            f'<span data-count-for="{table_id}">{len(table.rows)} visible</span>',
            '</div>',
            '<div class="table-wrap">',
            f'<table id="{table_id}">',
            "<thead><tr>",
        ]
    )
    for column in table.columns:
        parts.append(f"<th>{esc(column)}</th>")
    parts.append("</tr></thead><tbody>")

    column_count = len(table.columns)
    for row in table.rows:
        normalized = row[:column_count] + [""] * max(0, column_count - len(row))
        parts.append("<tr>")
        for cell in normalized:
            display = shorten(cell, max_cell_chars)
            title_attr = f' title="{esc(cell)}"' if display != cell else ""
            parts.append(f"<td{title_attr}>{esc(display)}</td>")
        parts.append("</tr>")

    parts.extend(["</tbody></table>", "</div>", "</details>"])
    return "\n".join(parts)


def render_html(tables: list[CsvTable], reports_dir: Path, stamp: str, max_cell_chars: int) -> str:
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    title = f"Software CSV Reports {stamp}" if stamp else "Software CSV Reports"
    total_rows = sum(len(table.rows) for table in tables)
    sections = "\n".join(
        render_table(table, index, reports_dir, max_cell_chars)
        for index, table in enumerate(tables, 1)
    )
    nav_items = "\n".join(
        f'<a href="#table-{index}">{esc(table.title)} <small>{len(table.rows)}</small></a>'
        for index, table in enumerate(tables, 1)
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0f141b;
      --panel: #151c25;
      --panel-2: #101720;
      --text: #e8edf4;
      --muted: #9aa8b8;
      --line: #2a3544;
      --accent: #7dd3fc;
      --danger: #fca5a5;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 "Segoe UI", Arial, sans-serif;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 3;
      padding: 18px 24px;
      background: rgba(15, 20, 27, 0.96);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(8px);
    }}
    h1 {{
      margin: 0 0 4px;
      font-size: 22px;
      font-weight: 650;
    }}
    .summary {{
      color: var(--muted);
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 14px 24px 4px;
    }}
    nav a {{
      color: var(--text);
      text-decoration: none;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      padding: 7px 9px;
    }}
    nav small {{
      color: var(--muted);
      margin-left: 5px;
    }}
    main {{ padding: 12px 24px 40px; }}
    details.report {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      margin: 0 0 18px;
      overflow: hidden;
    }}
    summary {{
      cursor: pointer;
      padding: 12px 14px;
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 16px;
      background: var(--panel-2);
      border-bottom: 1px solid var(--line);
      font-weight: 650;
    }}
    summary small {{ color: var(--muted); font-weight: 500; }}
    .report-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      padding: 10px 14px 0;
      color: var(--muted);
    }}
    .report-meta a {{ color: var(--accent); }}
    code {{
      color: var(--muted);
      white-space: normal;
      word-break: break-all;
    }}
    .table-tools {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      padding: 10px 14px;
    }}
    input[type="search"] {{
      min-width: min(420px, 100%);
      flex: 1;
      color: var(--text);
      background: #0b1118;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
    }}
    button {{
      color: var(--text);
      background: #1f2937;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      cursor: pointer;
    }}
    .table-tools span {{ color: var(--muted); }}
    .table-wrap {{
      max-height: 72vh;
      overflow: auto;
      border-top: 1px solid var(--line);
    }}
    table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      min-width: 900px;
    }}
    th, td {{
      text-align: left;
      vertical-align: top;
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      padding: 7px 9px;
      word-break: break-word;
    }}
    th {{
      position: sticky;
      top: 0;
      z-index: 2;
      background: #1b2531;
      color: #f8fafc;
      font-weight: 650;
    }}
    td {{ color: #dbe5ef; }}
    tr:nth-child(even) td {{ background: rgba(255, 255, 255, 0.018); }}
    tr[hidden] {{ display: none; }}
    .error {{ color: var(--danger); padding: 0 14px 14px; }}
    .empty {{ color: var(--muted); padding: 0 14px 14px; }}
    @media (max-width: 700px) {{
      header, nav, main {{ padding-left: 12px; padding-right: 12px; }}
      summary {{ align-items: flex-start; flex-direction: column; gap: 4px; }}
      table {{ min-width: 760px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{esc(title)}</h1>
    <div class="summary">
      <span>Generated: {esc(generated_at)}</span>
      <span>CSV files: {len(tables)}</span>
      <span>Total rows: {total_rows}</span>
    </div>
  </header>
  <nav>{nav_items}</nav>
  <main>
    {sections}
  </main>
  <script>
    function updateFilter(input) {{
      const table = document.getElementById(input.dataset.target);
      if (!table) return;
      const query = input.value.trim().toLowerCase();
      let visible = 0;
      for (const row of table.tBodies[0].rows) {{
        const show = !query || row.textContent.toLowerCase().includes(query);
        row.hidden = !show;
        if (show) visible += 1;
      }}
      const counter = document.querySelector(`[data-count-for="${{table.id}}"]`);
      if (counter) counter.textContent = `${{visible}} visible`;
    }}
    for (const input of document.querySelectorAll('input[type="search"][data-target]')) {{
      input.addEventListener('input', () => updateFilter(input));
    }}
    for (const button of document.querySelectorAll('button[data-clear]')) {{
      button.addEventListener('click', () => {{
        const input = document.querySelector(`input[data-target="${{button.dataset.clear}}"]`);
        if (input) {{
          input.value = '';
          updateFilter(input);
          input.focus();
        }}
      }});
    }}
  </script>
</body>
</html>
"""


def default_output_path(reports_dir: Path, stamp: str) -> Path:
    suffix = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    return reports_dir / f"csv_report_view_{suffix}.html"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert Software analyzer CSV reports to one static HTML file.")
    parser.add_argument("--reports-dir", default="", help="Reports directory. Defaults to Software/reports.")
    parser.add_argument("--timestamp", default="", help="Report timestamp to convert, for example 20260518_222523.")
    parser.add_argument("--all", action="store_true", help="Convert every CSV in the reports directory.")
    parser.add_argument("--csv", nargs="*", default=[], help="Explicit CSV paths or names to convert.")
    parser.add_argument("--output", default="", help="Output HTML path. Defaults to reports/csv_report_view_<timestamp>.html.")
    parser.add_argument("--max-cell-chars", type=int, default=900, help="Trim long displayed cell values; full value stays in the title tooltip. Use 0 for no trim.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = software_root()
    reports_dir = resolve_report_path(args.reports_dir, root, root / "reports") if args.reports_dir else root / "reports"
    reports_dir = reports_dir.resolve()
    if not reports_dir.is_dir():
        print(f"[csv-html] reports directory not found: {reports_dir}")
        return 2

    csv_files, stamp = pick_csv_files(
        reports_dir,
        timestamp=args.timestamp,
        include_all=args.all,
        explicit_csvs=args.csv,
        root=root,
    )
    csv_files = [path for path in csv_files if path.suffix.lower() == ".csv"]
    if not csv_files:
        print("[csv-html] no CSV files found.")
        return 2

    tables = [read_csv_table(path) for path in csv_files]
    output_path = resolve_report_path(args.output, root, reports_dir) if args.output else default_output_path(reports_dir, stamp)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_html(tables, reports_dir, stamp, args.max_cell_chars), encoding="utf-8")

    print(f"[csv-html] converted CSV files: {len(csv_files)}")
    print(f"[csv-html] wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
