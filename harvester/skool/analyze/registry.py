# Analysis registration and execution.
#
# Each analysis is a function that takes a Context and returns a Result.
# If the analysis is not possible with the available data, it returns None
# instead of raising an error.

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np
import pandas as pd

DEFAULT_GROUP = "General"


def _scalar(value: Any) -> Any:
    """Converts a value to a simple Python scalar."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return None if math.isnan(number) else number
    if isinstance(value, (np.str_,)):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    return value


# ────────────── analysis output ──────────────


@dataclass
class Result:
    """Output of one analysis: text, tables, charts, and metrics."""

    key: str
    title: str
    group: str = DEFAULT_GROUP
    lines: list[str] = field(default_factory=list)
    tables: list[tuple[str, pd.DataFrame]] = field(default_factory=list)
    charts: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    duration: float = 0.0

    # ── text ──
    def line(self, text: Any = "") -> "Result":
        self.lines.append("" if text is None else str(text))
        return self

    def bullet(self, text: Any) -> "Result":
        self.lines.append(f"- {text}")
        return self

    def blank(self) -> "Result":
        self.lines.append("")
        return self

    def note(self, text: Any) -> "Result":
        self.notes.append(str(text))
        return self

    # ── tables ──
    def table(self, caption: str, frame: Any) -> "Result":
        if frame is None:
            return self
        if not isinstance(frame, pd.DataFrame):
            frame = pd.DataFrame(frame)
        if frame.empty:
            return self
        self.tables.append((str(caption), frame.reset_index(drop=True)))
        return self

    # ── charts ──
    def chart(self, path: Any) -> "Result":
        if path:
            self.charts.append(str(path))
        return self

    # ── metrics ──
    def metric(self, name: str, value: Any) -> "Result":
        self.metrics[str(name)] = _scalar(value)
        return self

    @property
    def empty(self) -> bool:
        return not (self.lines or self.tables or self.charts or self.metrics or self.notes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "group": self.group,
            "lines": list(self.lines),
            "notes": list(self.notes),
            "charts": list(self.charts),
            "metrics": dict(self.metrics),
            "error": self.error,
            "duration": self.duration,
            "table_count": len(self.tables),
        }


# ──────────────── execution context ────────────────


@dataclass
class Context:
    """Data + chart maker + settings passed to all analyses."""

    data: Any
    charts: Any
    top: int = 20
    min_group: int = 5

    @property
    def groups(self) -> pd.DataFrame:
        return getattr(self.data, "groups", pd.DataFrame())

    @property
    def users(self) -> pd.DataFrame:
        return getattr(self.data, "users", pd.DataFrame())

    @property
    def links(self) -> pd.DataFrame:
        return getattr(self.data, "user_groups", pd.DataFrame())

    @property
    def paid(self) -> pd.DataFrame:
        return getattr(self.data, "paid", pd.DataFrame())

    @property
    def free(self) -> pd.DataFrame:
        return getattr(self.data, "free", pd.DataFrame())

    def frame(self, name: str) -> pd.DataFrame:
        """Access by name (groups / users / user_groups / links / paid / free)."""
        alias = {"links": "user_groups"}
        target = alias.get(name, name)
        value = getattr(self.data, target, None)
        if isinstance(value, pd.DataFrame):
            return value
        return pd.DataFrame()


# ───────────────── registry ──────────────────

AnalysisFn = Callable[[Context], Result | None]


@dataclass
class AnalysisSpec:
    key: str
    title: str
    group: str
    needs: tuple[str, ...]
    min_rows: int
    func: AnalysisFn
    order: int = 0


REGISTRY: dict[str, AnalysisSpec] = {}


def analysis(
    key: str,
    title: str,
    group: str = DEFAULT_GROUP,
    needs: Sequence[str] = ("groups",),
    min_rows: int = 1,
) -> Callable[[AnalysisFn], AnalysisFn]:
    """Decorator that registers an analysis."""

    def decorator(func: AnalysisFn) -> AnalysisFn:
        if key in REGISTRY:
            raise ValueError(f"Duplicate analysis: {key}")
        REGISTRY[key] = AnalysisSpec(
            key=key,
            title=title,
            group=group,
            needs=tuple(needs),
            min_rows=int(min_rows),
            func=func,
            order=len(REGISTRY),
        )
        return func

    return decorator


def new_result(spec: AnalysisSpec) -> Result:
    return Result(key=spec.key, title=spec.title, group=spec.group)


def ordered_specs() -> list[AnalysisSpec]:
    """Analyses sorted by group, then registration order."""
    return sorted(REGISTRY.values(), key=lambda spec: (spec.group, spec.order))


def groups_of_analyses() -> dict[str, list[AnalysisSpec]]:
    grouped: dict[str, list[AnalysisSpec]] = {}
    for spec in ordered_specs():
        grouped.setdefault(spec.group, []).append(spec)
    return grouped


def _matches_group(spec: AnalysisSpec, tokens: Iterable[str], names: list[str]) -> bool:
    group_lower = spec.group.lower()
    for token in tokens:
        clean = str(token).strip().lower()
        if not clean:
            continue
        if clean in group_lower:
            return True
        if clean.isdigit() and 1 <= int(clean) <= len(names) and names[int(clean) - 1] == spec.group:
            return True
    return False


def resolve(
    only: Sequence[str] | None = None,
    skip: Sequence[str] | None = None,
    only_groups: Sequence[str] | None = None,
) -> list[AnalysisSpec]:
    """The list of analyses to run."""
    specs = ordered_specs()
    names = list(groups_of_analyses().keys())

    if only:
        wanted = {str(item).strip() for item in only if str(item).strip()}
        unknown = wanted - set(REGISTRY)
        if unknown:
            raise KeyError(
                "Unknown analysis: " + ", ".join(sorted(unknown))
            )
        specs = [spec for spec in specs if spec.key in wanted]
    if only_groups:
        specs = [spec for spec in specs if _matches_group(spec, only_groups, names)]
    if skip:
        unwanted = {str(item).strip() for item in skip if str(item).strip()}
        specs = [spec for spec in specs if spec.key not in unwanted]
    return specs


# ─────────────────── execution ───────────────────


def run_analyses(
    ctx: Context,
    only: Sequence[str] | None = None,
    skip: Sequence[str] | None = None,
    only_groups: Sequence[str] | None = None,
    on_result: Callable[[Result], None] | None = None,
) -> list[Result]:
    """Runs all analyses; an error in one analysis does not stop the others."""
    results: list[Result] = []
    for spec in resolve(only=only, skip=skip, only_groups=only_groups):
        result = new_result(spec)
        started = time.perf_counter()
        try:
            missing = [name for name in spec.needs if len(ctx.frame(name)) < spec.min_rows]
            if missing:
                result.note(
                    "Not enough data for this analysis (empty or low-row table: "
                    + ", ".join(missing)
                    + ")"
                )
            else:
                if hasattr(ctx.charts, "prefix"):
                    ctx.charts.prefix = spec.key
                produced = spec.func(ctx)
                if produced is not None:
                    result = produced
                    result.key, result.title, result.group = spec.key, spec.title, spec.group
                    if result.empty:
                        result.note("Nothing found to display.")
                else:
                    result.note(
                        "This analysis could not be run with the available data (required columns were empty or missing)."
                    )
        except Exception as exc:  # noqa: BLE001 - the error stays within this analysis only
            result.error = f"{type(exc).__name__}: {exc}"
        result.duration = time.perf_counter() - started
        results.append(result)
        if on_result is not None:
            on_result(result)
    return results


def all_metrics(results: Sequence[Result]) -> dict[str, Any]:
    """All metrics keyed as "key.metric"."""
    merged: dict[str, Any] = {}
    for result in results:
        for name, value in result.metrics.items():
            merged[f"{result.key}.{name}"] = value
    return merged


def metrics_table(results: Sequence[Result]) -> pd.DataFrame:
    """Metrics as a table (for CSV and manual review)."""
    rows = [
        {"analysis": result.key, "group": result.group, "metric": name, "value": value}
        for result in results
        for name, value in result.metrics.items()
    ]
    return pd.DataFrame(rows)


def catalog() -> pd.DataFrame:
    """Catalog of available analyses."""
    rows = [
        {
            "key": spec.key,
            "title": spec.title,
            "group": spec.group,
            "needs": ", ".join(spec.needs),
        }
        for spec in ordered_specs()
    ]
    return pd.DataFrame(rows)
