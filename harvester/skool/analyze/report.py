"""Output: console text, Markdown report, and JSON output.

No extra dependencies are needed (markdown tables are rendered manually,
so we do not need tabulate).
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from .registry import Result, all_metrics

MAX_TABLE_ROWS = 40

PERCENT_HINTS = ("share", "pct", "ratio", "rate", "cumulative", "coverage")
MONEY_HINTS = ("price", "usd", "mrr", "revenue", "arpu")


# ─────────────── cell formatting ───────────────


def _is_nan(value: Any) -> bool:
    return value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value))


def _fmt_cell(value: Any, column: str) -> str:
    name = str(column).lower()
    if _is_nan(value):
        return "—"
    if isinstance(value, (bool, np.bool_)):
        return "✓" if value else "✗"
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,}"
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if any(hint in name for hint in PERCENT_HINTS) and abs(number) <= 1.5:
            return f"{number * 100:.1f}%"
        if any(hint in name for hint in MONEY_HINTS):
            return f"${number:,.2f}"
        if number.is_integer() and abs(number) >= 1000:
            return f"{int(number):,}"
        if abs(number) >= 1000:
            return f"{number:,.1f}"
        if abs(number) < 0.005 and number != 0:
            return f"{number:.2e}"
        return f"{number:,.3f}".rstrip("0").rstrip(".")
    return str(value)


def format_frame(frame: pd.DataFrame, max_rows: int = MAX_TABLE_ROWS) -> pd.DataFrame:
    """A string, human-readable version of the table."""
    trimmed = frame.head(max_rows)
    data = {
        str(column): [_fmt_cell(value, column) for value in trimmed[column]]
        for column in trimmed.columns
    }
    return pd.DataFrame(data, index=range(len(trimmed)))


def md_table(frame: pd.DataFrame, max_rows: int = MAX_TABLE_ROWS) -> str:
    if frame is None or frame.empty:
        return ""
    shown = format_frame(frame, max_rows)
    header = "| " + " | ".join(shown.columns) + " |"
    divider = "| " + " | ".join(["---"] * len(shown.columns)) + " |"
    rows = [
        "| " + " | ".join(str(value).replace("|", "\\|") for value in record) + " |"
        for record in shown.itertuples(index=False, name=None)
    ]
    extra = len(frame) - len(shown)
    tail = f"\n\n_({extra:,} more rows not shown)_" if extra > 0 else ""
    return "\n".join([header, divider, *rows]) + tail


def console_table(frame: pd.DataFrame, max_rows: int = MAX_TABLE_ROWS, indent: str = "   ") -> str:
    if frame is None or frame.empty:
        return ""
    shown = format_frame(frame, max_rows)
    widths = [
        max(len(str(column)), *(len(str(v)) for v in shown[column])) if len(shown) else len(str(column))
        for column in shown.columns
    ]
    lines = [
        indent + "  ".join(str(column).ljust(width) for column, width in zip(shown.columns, widths)),
        indent + "  ".join("-" * width for width in widths),
    ]
    for record in shown.itertuples(index=False, name=None):
        lines.append(indent + "  ".join(str(value).ljust(width) for value, width in zip(record, widths)))
    extra = len(frame) - len(shown)
    if extra > 0:
        lines.append(f"{indent}... {extra:,} more rows")
    return "\n".join(lines)


# ──────────── executive summary ────────────


def _pct(value: Any) -> str:
    return "—" if _is_nan(value) else f"{float(value) * 100:.1f}%"


def _money(value: Any) -> str:
    return "—" if _is_nan(value) else f"${float(value):,.0f}"


def _int(value: Any) -> str:
    return "—" if _is_nan(value) else f"{int(round(float(value))):,}"


def _num(value: Any) -> str:
    return "—" if _is_nan(value) else f"{float(value):,.3f}".rstrip("0").rstrip(".")


HIGHLIGHTS: list[tuple[str, str, Any]] = [
    ("overview.groups", "Groups analyzed", _int),
    ("overview.users", "Users (owners) in data", _int),
    ("overview.detail_coverage", "Share of fully detailed groups", _pct),
    ("price_distribution.free_share", "Share of free groups", _pct),
    ("price_distribution.median_paid_price", "Median paid group price", _money),
    ("price_distribution.top_tier", "Most populated price range", str),
    ("members_distribution.median_members", "Median number of members", _int),
    ("members_distribution.gini", "Gini of member distribution (inequality)", _num),
    ("members_distribution.top_1pct", "Share of total members held by top 1%", _pct),
    ("price_vs_members.spearman", "Correlation between price and member count (Spearman)", _num),
    ("public_private.public_share", "Share of public groups", _pct),
    ("owner_portfolio.multi_group_share", "Share of owners with more than one group", _pct),
    ("market_size.total_est_mrr", "Estimated total monthly revenue (very rough)", _money),
]


def highlights(results: Sequence[Result]) -> list[str]:
    """A few headline lines drawn from the analyses' metrics."""
    metrics = all_metrics(results)
    lines: list[str] = []
    for key, label, formatter in HIGHLIGHTS:
        if key in metrics and metrics[key] is not None:
            lines.append(f"{label}: **{formatter(metrics[key])}**")
    return lines


# ────────────── console ───────────────

RULE = "─" * 78


def render_console(results: Sequence[Result], info: dict[str, Any]) -> str:
    out: list[str] = []
    out.append(RULE)
    out.append("  Skool data analysis")
    out.append(
        "  Source: {source} | Groups: {groups:,} | Users: {users:,} | Paid: {paid_groups:,}".format(
            **{**{"source": "?", "groups": 0, "users": 0, "paid_groups": 0}, **info}
        )
    )
    if info.get("filters"):
        out.append("  Filters: " + " , ".join(info["filters"]))
    out.append(RULE)

    headline = highlights(results)
    if headline:
        out.append("")
        out.append("■ Executive summary")
        for line in headline:
            out.append("   • " + line.replace("**", ""))

    current_group = None
    for result in results:
        if result.group != current_group:
            current_group = result.group
            out.append("")
            out.append(f"═══ {current_group} " + "═" * max(0, 70 - len(current_group)))
        out.append("")
        out.append(f"▶ {result.title}  [{result.key}]")
        if result.error:
            out.append(f"   ⚠ error: {result.error}")
        for note in result.notes:
            out.append(f"   ℹ {note}")
        for line in result.lines:
            out.append(f"   {line}" if line else "")
        for caption, frame in result.tables:
            out.append("")
            out.append(f"   ▪ {caption}")
            out.append(console_table(frame))
        for path in result.charts:
            out.append(f"   🖼 {path}")
    out.append("")
    out.append(RULE)
    return "\n".join(out)


# ───────────── Markdown ──────────────


def write_markdown(
    results: Sequence[Result],
    out_dir: str | Path,
    info: dict[str, Any],
    filename: str = "report.md",
) -> Path:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / filename

    lines: list[str] = []
    lines.append("# Skool data analysis report")
    lines.append("")
    lines.append(
        f"Data source: `{info.get('source', '?')}` — "
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )
    lines.append("")
    lines.append(
        "| Table | Row count |\n| --- | --- |\n"
        f"| groups | {info.get('groups', 0):,} |\n"
        f"| users | {info.get('users', 0):,} |\n"
        f"| user_groups | {info.get('user_groups', 0):,} |\n"
        f"| Paid groups | {info.get('paid_groups', 0):,} |"
    )
    if info.get("filters"):
        lines.append("")
        lines.append("**Applied filters:** " + " , ".join(info["filters"]))

    headline = highlights(results)
    if headline:
        lines.append("")
        lines.append("## Executive summary")
        lines.append("")
        for item in headline:
            lines.append(f"- {item}")

    lines.append("")
    lines.append("## Index")
    lines.append("")
    for result in results:
        anchor = result.key.replace("_", "-")
        lines.append(f"- [{result.title}](#{anchor}) — `{result.key}`")

    current_group = None
    for result in results:
        if result.group != current_group:
            current_group = result.group
            lines.append("")
            lines.append(f"## {current_group}")
        lines.append("")
        lines.append(f'<a id="{result.key.replace("_", "-")}"></a>')
        lines.append(f"### {result.title}")
        lines.append("")
        if result.error:
            lines.append(f"> ⚠️ Error in this analysis: `{result.error}`")
            lines.append("")
        for note in result.notes:
            lines.append(f"> ℹ️ {note}")
            lines.append("")
        for line in result.lines:
            lines.append(line if line else "")
        for caption, frame in result.tables:
            lines.append("")
            lines.append(f"**{caption}**")
            lines.append("")
            lines.append(md_table(frame))
        for chart in result.charts:
            try:
                relative = Path(chart).relative_to(target)
            except ValueError:
                relative = Path(chart)
            lines.append("")
            lines.append(f"![{result.title}]({relative.as_posix()})")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ─────────────── JSON ────────────────


def _jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return None if math.isnan(number) else number
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).isoformat()
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(
    results: Sequence[Result],
    out_dir: str | Path,
    info: dict[str, Any],
    filename: str = "report.json",
) -> Path:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / filename
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": _jsonable(info),
        "metrics": _jsonable(all_metrics(results)),
        "analyses": [
            {
                "key": result.key,
                "title": result.title,
                "group": result.group,
                "lines": result.lines,
                "notes": result.notes,
                "error": result.error,
                "duration_seconds": round(result.duration, 3),
                "metrics": _jsonable(result.metrics),
                "charts": [str(chart) for chart in result.charts],
                "tables": {
                    caption: _jsonable(frame.head(MAX_TABLE_ROWS).to_dict(orient="records"))
                    for caption, frame in result.tables
                },
            }
            for result in results
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_tables(results: Sequence[Result], out_dir: str | Path) -> list[Path]:
    """Writes all analysis tables as CSV (for Excel and manual review)."""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for result in results:
        for index, (caption, frame) in enumerate(result.tables, start=1):
            safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in caption)[:40]
            path = target / f"{result.key}__{index}_{safe or 'table'}.csv"
            frame.to_csv(path, index=False)
            written.append(path)
    return written
