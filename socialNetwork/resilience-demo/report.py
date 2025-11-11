#!/usr/bin/env python3
"""Generate a static HTML report for the resilience demo."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional


def _load_results(results_dir: Path) -> List[Mapping[str, object]]:
    data: List[Mapping[str, object]] = []
    for path in sorted(results_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as fh:
            data.append(json.load(fh))
    return data


def _format_percentage(value: float) -> str:
    return f"{value * 100:.2f}%"


def _build_endpoint_rows(results: List[Mapping[str, object]]) -> Dict[str, Dict[str, Dict[str, float]]]:
    table: Dict[str, Dict[str, Dict[str, float]]] = {}
    for payload in results:
        summary = payload.get("summary")
        endpoints = payload.get("endpoints")
        if not isinstance(summary, dict) or "pfail" not in summary:
            continue
        if not isinstance(endpoints, dict):
            continue

        pfail = str(summary.get("pfail"))
        mode = summary.get("mode") or Path(summary.get("replicas_file", "")).stem or "unknown"
        mode_key = "repl" if mode == "repl" else "norepl"
        for endpoint, details in endpoints.items():
            if not isinstance(details, Mapping):
                continue
            table.setdefault(endpoint, {}).setdefault(pfail, {})[mode_key] = float(details.get("reliability", 0.0))
    return table


def _collect_pfails(table: Mapping[str, Mapping[str, Dict[str, float]]]) -> List[str]:
    pfails = set()
    for endpoint_data in table.values():
        pfails.update(endpoint_data.keys())
    return sorted(pfails, key=lambda v: float(v))


def _render_table(table: Mapping[str, Mapping[str, Dict[str, float]]]) -> str:
    pfails = _collect_pfails(table)
    header = "".join(
        f"<th colspan='2'>pfail={html.escape(p)}</th>" for p in pfails
    )
    rows: List[str] = [
        "<table>",
        "  <thead>",
        "    <tr><th rowspan='2'>Endpoint</th>" + header + "</tr>",
        "    <tr>" + "".join("<th>norepl</th><th>repl</th>" for _ in pfails) + "</tr>",
        "  </thead>",
        "  <tbody>",
    ]

    for endpoint in sorted(table.keys()):
        row_cells = [f"    <tr><td>{html.escape(endpoint)}</td>"]
        for pfail in pfails:
            data = table[endpoint].get(pfail, {})
            norepl = data.get("norepl")
            repl = data.get("repl")
            row_cells.append(
                f"<td class='norepl'>{_format_percentage(norepl) if norepl is not None else '–'}</td>"
            )
            row_cells.append(
                f"<td class='repl'>{_format_percentage(repl) if repl is not None else '–'}</td>"
            )
        row_cells.append("</tr>")
        rows.append("".join(row_cells))

    rows.append("  </tbody>")
    rows.append("</table>")
    return "\n".join(rows)


def _render_summary(summary_path: Optional[Path]) -> str:
    if not summary_path or not summary_path.exists():
        return "<p>No gate summary was generated.</p>"
    summary = json.loads(summary_path.read_text())
    status = "passed" if summary.get("passed") else "failed"
    reason = html.escape(summary.get("reason", ""))
    filters = summary.get("filters", [])
    if filters:
        filter_html = ", ".join(html.escape(flt) for flt in filters)
    else:
        filter_html = "(all endpoints)"
    return (
        "<section class='gate-summary'>"
        f"<h2>Gate status: <span class='{status}'>{status.upper()}</span></h2>"
        f"<p>{reason}</p>"
        f"<p>Threshold: {summary.get('threshold')} — Mode: {html.escape(summary.get('mode', 'any'))}</p>"
        f"<p>Filters: {filter_html}</p>"
        "</section>"
    )


def render_html(
    results_dir: Path,
    summary_path: Optional[Path],
    output_path: Path,
    title: str = "Social Network resilience demo",
) -> None:
    results = _load_results(results_dir)
    table = _build_endpoint_rows(results)
    table_markup = _render_table(table)
    summary_markup = _render_summary(summary_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
      body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #111; background: #fafafa; }}
      h1 {{ margin-top: 0; }}
      table {{ border-collapse: collapse; width: 100%; margin-top: 1.5rem; }}
      th, td {{ border: 1px solid #ccc; padding: 0.5rem; text-align: center; }}
      thead th {{ background: #f0f0f0; }}
      td.norepl {{ background: #ffe7d6; }}
      td.repl {{ background: #e0f7ec; }}
      .gate-summary {{ padding: 1rem; border-left: 4px solid #888; background: #fff; }}
      .gate-summary .passed {{ color: #0a7d25; }}
      .gate-summary .failed {{ color: #c2272d; }}
      footer {{ margin-top: 2rem; font-size: 0.85rem; color: #555; }}
      code {{ background: rgba(0,0,0,0.05); padding: 0.2rem 0.3rem; border-radius: 4px; }}
    </style>
  </head>
  <body>
    <h1>{title}</h1>
    {summary_markup}
    <section>
      <h2>Endpoint reliability</h2>
      {table_markup}
    </section>
    <footer>
      Generated from offline artifacts under <code>socialNetwork/resilience-demo/</code>.
    </footer>
  </body>
</html>
""".format(
            title=html.escape(title),
            summary_markup=summary_markup,
            table_markup=table_markup,
        )
    )


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a static HTML report")
    parser.add_argument("--results", required=True, type=Path, help="Directory containing simulation outputs")
    parser.add_argument("--summary", type=Path, help="Gate summary JSON file")
    parser.add_argument("--html", required=True, type=Path, help="Where to write the HTML report")
    parser.add_argument("--title", default="Social Network resilience demo")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    render_html(args.results, args.summary, args.html, args.title)
    print(f"[report] HTML report written to {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
