"""Skool data analysis module (EDA).

Usage:
    python -m skool.analyze --list
    python -m skool.analyze
    python -m skool.analyze --only price_distribution price_vs_members --no-charts

From within code (e.g., a notebook):
    from skool.analyze import run_analysis
    outcome = run_analysis(out_dir="analysis_out", charts=False)
    print(outcome["metrics"]["price_vs_members.spearman"])

Imports are lazy, so the package can be imported even without
pandas/matplotlib installed and gives a readable error.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "run_analysis",
    "main",
    "Dataset",
    "ChartMaker",
    "Context",
    "Result",
    "REGISTRY",
    "catalog",
    "run_analyses",
    "loader",
    "stats",
    "charts",
    "report",
    "registry",
]

_LAZY = {
    "run_analysis": ("skool.analyze.cli", "run_analysis"),
    "main": ("skool.analyze.cli", "main"),
    "Dataset": ("skool.analyze.loader", "Dataset"),
    "ChartMaker": ("skool.analyze.charts", "ChartMaker"),
    "Context": ("skool.analyze.registry", "Context"),
    "Result": ("skool.analyze.registry", "Result"),
    "REGISTRY": ("skool.analyze.registry", "REGISTRY"),
    "catalog": ("skool.analyze.registry", "catalog"),
    "run_analyses": ("skool.analyze.registry", "run_analyses"),
}

_MODULES = ("loader", "stats", "charts", "report", "registry", "analyses", "cli")


def __getattr__(name: str) -> Any:
    from importlib import import_module

    if name in _LAZY:
        module_name, attribute = _LAZY[name]
        return getattr(import_module(module_name), attribute)
    if name in _MODULES:
        return import_module(f"skool.analyze.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(_MODULES))
