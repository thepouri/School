"""Chart drawing (matplotlib, no GUI window).

Rules:

* Uses the Agg backend so it also works on headless servers.
* Text on charts is **English**; matplotlib does not render Persian
  correctly without fonts and shaping (analytical Persian text goes in the
  report, not on the chart).
* If matplotlib is not installed or charts are disabled, all methods return
  `None` and the text analysis continues without errors.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

log = logging.getLogger("skool.analyze.charts")

try:  # matplotlib is optional
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    MATPLOTLIB_OK = True
except Exception:  # noqa: BLE001
    MATPLOTLIB_OK = False

PALETTE = [
    "#4C72B0",
    "#DD8452",
    "#55A868",
    "#C44E52",
    "#8172B3",
    "#937860",
    "#DA8BC3",
    "#8C8C8C",
    "#CCB974",
    "#64B5CD",
]
GRID = {"color": "#DDDDDD", "linewidth": 0.8}


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]+", "_", str(text)).strip("_").lower()
    return cleaned or "chart"


def _thousands(value: float, _pos: Any = None) -> str:
    value = float(value)
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(value) >= limit:
            return f"{value / limit:.1f}{suffix}".replace(".0", "")
    return f"{value:,.0f}"


class ChartMaker:
    """Chart maker: each method produces a PNG file and returns its path."""

    def __init__(
        self,
        out_dir: str | Path,
        enabled: bool = True,
        dpi: int = 140,
        image_format: str = "png",
    ) -> None:
        self.dir = Path(out_dir)
        self.enabled = bool(enabled and MATPLOTLIB_OK)
        self.dpi = dpi
        self.format = image_format
        self.prefix = ""
        self.made: list[Path] = []
        if enabled and not MATPLOTLIB_OK:
            log.warning("matplotlib is not installed — charts are skipped")

    # ────────── infrastructure ──────────

    def _start(self, size: tuple[float, float] = (9.0, 5.0)):
        fig, ax = plt.subplots(figsize=size)
        ax.grid(axis="both", **GRID)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        return fig, ax

    def _save(self, fig, name: str, title: str | None = None) -> Path | None:
        filename = f"{_slug(self.prefix)}__{_slug(name)}.{self.format}" if self.prefix else f"{_slug(name)}.{self.format}"
        path = self.dir / filename
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            fig.tight_layout()
            fig.savefig(path, dpi=self.dpi, bbox_inches="tight", facecolor="white")
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not save chart %s: %s", name, exc)
            path = None
        finally:
            plt.close(fig)
        if path:
            self.made.append(path)
        return path

    @staticmethod
    def _labels(values: Sequence[Any]) -> list[str]:
        return ["—" if v is None else str(v) for v in values]

    @staticmethod
    def _numbers(values: Sequence[Any]) -> np.ndarray:
        return np.asarray([np.nan if v is None else float(v) for v in values], dtype=float)

    def _annotate_bars(self, ax, bars, values: np.ndarray, percent: bool) -> None:
        span = np.nanmax(np.abs(values)) if values.size else 0
        for bar, value in zip(bars, values):
            if not np.isfinite(value):
                continue
            text = f"{value * 100:.1f}%" if percent else _thousands(value)
            ax.annotate(
                text,
                (bar.get_x() + bar.get_width() / 2, value),
                textcoords="offset points",
                xytext=(0, 3 if value >= 0 else -11),
                ha="center",
                fontsize=8,
                color="#333333",
            )
        if span:
            ax.margins(y=0.12)

    # ────────── charts ──────────

    def bar(
        self,
        labels: Sequence[Any],
        values: Sequence[Any],
        name: str,
        title: str,
        xlabel: str = "",
        ylabel: str = "",
        rotate: int = 0,
        percent: bool = False,
        log_y: bool = False,
        color: str | None = None,
        annotate: bool = True,
        size: tuple[float, float] = (9.0, 5.0),
    ) -> Path | None:
        if not self.enabled or not len(labels):
            return None
        data = self._numbers(values)
        fig, ax = self._start(size)
        bars = ax.bar(self._labels(labels), data, color=color or PALETTE[0], width=0.72)
        ax.set_title(title, fontsize=12, pad=12)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        if log_y:
            ax.set_yscale("log")
        elif annotate:
            self._annotate_bars(ax, bars, data, percent)
        if percent:
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v * 100:.0f}%"))
        else:
            ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
        if rotate:
            plt.setp(ax.get_xticklabels(), rotation=rotate, ha="right")
        return self._save(fig, name, title)

    def barh(
        self,
        labels: Sequence[Any],
        values: Sequence[Any],
        name: str,
        title: str,
        xlabel: str = "",
        percent: bool = False,
        color: str | None = None,
        size: tuple[float, float] | None = None,
    ) -> Path | None:
        if not self.enabled or not len(labels):
            return None
        data = self._numbers(values)
        height = max(3.2, 0.34 * len(labels) + 1.2)
        fig, ax = self._start(size or (9.0, height))
        positions = np.arange(len(labels))
        ax.barh(positions, data, color=color or PALETTE[2], height=0.68)
        ax.set_yticks(positions, self._labels(labels), fontsize=9)
        ax.invert_yaxis()
        ax.set_title(title, fontsize=12, pad=12)
        ax.set_xlabel(xlabel)
        formatter = (lambda v, _p: f"{v * 100:.0f}%") if percent else _thousands
        ax.xaxis.set_major_formatter(FuncFormatter(formatter))
        for position, value in zip(positions, data):
            if np.isfinite(value):
                text = f"{value * 100:.1f}%" if percent else _thousands(value)
                ax.annotate(
                    text,
                    (value, position),
                    textcoords="offset points",
                    xytext=(4, 0),
                    va="center",
                    fontsize=8,
                    color="#333333",
                )
        ax.margins(x=0.12)
        return self._save(fig, name, title)

    def grouped_bar(
        self,
        labels: Sequence[Any],
        series: Mapping[str, Sequence[Any]],
        name: str,
        title: str,
        ylabel: str = "",
        rotate: int = 0,
        percent: bool = False,
        log_y: bool = False,
    ) -> Path | None:
        if not self.enabled or not len(labels) or not series:
            return None
        fig, ax = self._start((max(9.0, 0.9 * len(labels) + 3), 5.2))
        positions = np.arange(len(labels))
        width = 0.8 / len(series)
        for index, (label, values) in enumerate(series.items()):
            ax.bar(
                positions + index * width - 0.4 + width / 2,
                self._numbers(values),
                width=width,
                label=label,
                color=PALETTE[index % len(PALETTE)],
            )
        ax.set_xticks(positions, self._labels(labels))
        ax.set_title(title, fontsize=12, pad=12)
        ax.set_ylabel(ylabel)
        if log_y:
            ax.set_yscale("log")
        formatter = (lambda v, _p: f"{v * 100:.0f}%") if percent else _thousands
        ax.yaxis.set_major_formatter(FuncFormatter(formatter))
        ax.legend(frameon=False, fontsize=9)
        if rotate:
            plt.setp(ax.get_xticklabels(), rotation=rotate, ha="right")
        return self._save(fig, name, title)

    def stacked_bar(
        self,
        labels: Sequence[Any],
        series: Mapping[str, Sequence[Any]],
        name: str,
        title: str,
        ylabel: str = "",
        rotate: int = 0,
        percent: bool = False,
    ) -> Path | None:
        if not self.enabled or not len(labels) or not series:
            return None
        fig, ax = self._start((max(9.0, 0.75 * len(labels) + 3), 5.4))
        bottom = np.zeros(len(labels))
        for index, (label, values) in enumerate(series.items()):
            data = np.nan_to_num(self._numbers(values))
            ax.bar(
                self._labels(labels),
                data,
                bottom=bottom,
                label=label,
                color=PALETTE[index % len(PALETTE)],
                width=0.72,
            )
            bottom += data
        ax.set_title(title, fontsize=12, pad=12)
        ax.set_ylabel(ylabel)
        formatter = (lambda v, _p: f"{v * 100:.0f}%") if percent else _thousands
        ax.yaxis.set_major_formatter(FuncFormatter(formatter))
        ax.legend(frameon=False, fontsize=9, ncols=min(4, len(series)))
        if rotate:
            plt.setp(ax.get_xticklabels(), rotation=rotate, ha="right")
        return self._save(fig, name, title)

    def hist(
        self,
        values: Sequence[Any],
        name: str,
        title: str,
        xlabel: str = "",
        ylabel: str = "count",
        bins: int = 40,
        log_x: bool = False,
        log_y: bool = False,
        color: str | None = None,
    ) -> Path | None:
        if not self.enabled:
            return None
        data = self._numbers(values)
        data = data[np.isfinite(data)]
        if log_x:
            data = data[data > 0]
        if data.size < 2:
            return None
        fig, ax = self._start()
        if log_x:
            edges = np.logspace(np.log10(data.min()), np.log10(data.max()), bins)
            ax.hist(data, bins=edges, color=color or PALETTE[0], edgecolor="white")
            ax.set_xscale("log")
        else:
            ax.hist(data, bins=bins, color=color or PALETTE[0], edgecolor="white")
        if log_y:
            ax.set_yscale("log")
        median = float(np.median(data))
        ax.axvline(median, color=PALETTE[3], linestyle="--", linewidth=1.4, label=f"median = {_thousands(median)}")
        ax.legend(frameon=False, fontsize=9)
        ax.set_title(title, fontsize=12, pad=12)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        return self._save(fig, name, title)

    def scatter(
        self,
        x: Sequence[Any],
        y: Sequence[Any],
        name: str,
        title: str,
        xlabel: str = "",
        ylabel: str = "",
        log_x: bool = False,
        log_y: bool = False,
        trend: bool = True,
        alpha: float = 0.35,
        color: str | None = None,
    ) -> Path | None:
        if not self.enabled:
            return None
        xs = self._numbers(x)
        ys = self._numbers(y)
        mask = np.isfinite(xs) & np.isfinite(ys)
        if log_x:
            mask &= xs > 0
        if log_y:
            mask &= ys > 0
        xs, ys = xs[mask], ys[mask]
        if xs.size < 3:
            return None
        fig, ax = self._start((8.6, 5.6))
        ax.scatter(xs, ys, s=18, alpha=alpha, color=color or PALETTE[0], edgecolors="none")
        if log_x:
            ax.set_xscale("log")
        if log_y:
            ax.set_yscale("log")
        if trend and xs.size >= 5:
            try:
                fx = np.log10(xs) if log_x else xs
                fy = np.log10(ys) if log_y else ys
                slope, intercept = np.polyfit(fx, fy, 1)
                grid = np.linspace(fx.min(), fx.max(), 50)
                fit = slope * grid + intercept
                ax.plot(
                    10**grid if log_x else grid,
                    10**fit if log_y else fit,
                    color=PALETTE[3],
                    linewidth=1.8,
                    label=f"trend (slope={slope:.2f})",
                )
                ax.legend(frameon=False, fontsize=9)
            except Exception:  # noqa: BLE001
                pass
        ax.set_title(title, fontsize=12, pad=12)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        if not log_y:
            ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
        if not log_x:
            ax.xaxis.set_major_formatter(FuncFormatter(_thousands))
        return self._save(fig, name, title)

    def line(
        self,
        x: Sequence[Any],
        series: Mapping[str, Sequence[Any]],
        name: str,
        title: str,
        xlabel: str = "",
        ylabel: str = "",
        rotate: int = 0,
        log_y: bool = False,
        marker: str = "o",
    ) -> Path | None:
        if not self.enabled or not len(x) or not series:
            return None
        fig, ax = self._start((10.0, 5.0))
        labels = self._labels(x)
        for index, (label, values) in enumerate(series.items()):
            ax.plot(
                labels,
                self._numbers(values),
                marker=marker,
                markersize=4,
                linewidth=1.8,
                label=label,
                color=PALETTE[index % len(PALETTE)],
            )
        if log_y:
            ax.set_yscale("log")
        ax.set_title(title, fontsize=12, pad=12)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
        if len(series) > 1:
            ax.legend(frameon=False, fontsize=9)
        step = max(1, len(labels) // 24)
        ax.set_xticks(np.arange(0, len(labels), step), labels[::step])
        if rotate:
            plt.setp(ax.get_xticklabels(), rotation=rotate, ha="right")
        return self._save(fig, name, title)

    def box(
        self,
        groups: Mapping[str, Sequence[Any]],
        name: str,
        title: str,
        ylabel: str = "",
        log_y: bool = True,
        rotate: int = 0,
    ) -> Path | None:
        if not self.enabled or not groups:
            return None
        data: list[np.ndarray] = []
        labels: list[str] = []
        for label, values in groups.items():
            array = self._numbers(values)
            array = array[np.isfinite(array)]
            if log_y:
                array = array[array > 0]
            if array.size >= 3:
                data.append(array)
                labels.append(f"{label}\n(n={array.size:,})")
        if not data:
            return None
        fig, ax = self._start((max(7.5, 1.5 * len(data) + 2), 5.2))
        artists = ax.boxplot(data, patch_artist=True, showfliers=False, widths=0.55, tick_labels=labels)
        for index, patch in enumerate(artists["boxes"]):
            patch.set_facecolor(PALETTE[index % len(PALETTE)])
            patch.set_alpha(0.75)
        for median in artists["medians"]:
            median.set_color("#222222")
        if log_y:
            ax.set_yscale("log")
        ax.set_title(title, fontsize=12, pad=12)
        ax.set_ylabel(ylabel)
        if rotate:
            plt.setp(ax.get_xticklabels(), rotation=rotate, ha="right")
        return self._save(fig, name, title)

    def heatmap(
        self,
        matrix: Any,
        name: str,
        title: str,
        fmt: str = "{:.2f}",
        cmap: str = "RdBu_r",
        vmin: float | None = None,
        vmax: float | None = None,
        cbar_label: str = "",
    ) -> Path | None:
        """matrix is a DataFrame (index and columns become labels)."""
        if not self.enabled or matrix is None or getattr(matrix, "empty", True):
            return None
        values = matrix.to_numpy(dtype=float)
        rows, columns = values.shape
        fig, ax = plt.subplots(figsize=(max(6.0, 0.85 * columns + 3), max(4.0, 0.6 * rows + 2.4)))
        image = ax.imshow(values, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
        ax.set_xticks(np.arange(columns), [str(c) for c in matrix.columns], rotation=35, ha="right", fontsize=9)
        ax.set_yticks(np.arange(rows), [str(i) for i in matrix.index], fontsize=9)
        finite = values[np.isfinite(values)]
        threshold = (finite.max() + finite.min()) / 2 if finite.size else 0
        for i in range(rows):
            for j in range(columns):
                value = values[i, j]
                if not np.isfinite(value):
                    continue
                ax.text(
                    j,
                    i,
                    fmt.format(value),
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="white" if abs(value) > abs(threshold) * 1.35 else "#222222",
                )
        bar = fig.colorbar(image, ax=ax, shrink=0.85)
        if cbar_label:
            bar.set_label(cbar_label, fontsize=9)
        ax.set_title(title, fontsize=12, pad=12)
        return self._save(fig, name, title)

    def lorenz(
        self,
        x: Sequence[float],
        y: Sequence[float],
        name: str,
        title: str,
        xlabel: str = "cumulative share of groups",
        ylabel: str = "cumulative share of members",
        gini_value: float | None = None,
    ) -> Path | None:
        if not self.enabled or x is None or not len(x):
            return None
        fig, ax = self._start((6.4, 6.0))
        ax.plot([0, 1], [0, 1], linestyle="--", color="#999999", linewidth=1.2, label="perfect equality")
        label = "actual" if gini_value is None else f"actual (Gini = {gini_value:.3f})"
        ax.plot(x, y, color=PALETTE[0], linewidth=2.0, label=label)
        ax.fill_between(x, y, x, color=PALETTE[0], alpha=0.12)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_title(title, fontsize=12, pad=12)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.legend(frameon=False, fontsize=9, loc="upper left")
        return self._save(fig, name, title)
