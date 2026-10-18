"""EDA statistics — only numpy/pandas (no scipy).

What we have here:

* `correlate` — Pearson + Spearman + Pearson on log scale,
  plus Fisher confidence interval and approximate p-value
* `mann_whitney` — two-group comparison without assuming normality
  (normal approximation with tie correction) + Cliff's delta effect size
* `gini` / `lorenz` / `top_share` — concentration measures (what share of
  members is held by what share of groups)
* `describe` / `value_counts_table` / `group_summary` — reusable table builders

All functions return `None` for small/empty data instead of raising;
because mid-crawl any column may be empty.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

# normal quantile for 95% confidence
Z95 = 1.959963984540054


# ────────────────────── base ──────────────────────


def as_numeric(values: Any) -> pd.Series:
    """Converts anything to a numeric float series (non-numeric → NaN)."""
    series = values if isinstance(values, pd.Series) else pd.Series(list(values))
    if series.dtype == bool:
        return series.astype("float64")
    try:
        return pd.to_numeric(series, errors="coerce").astype("float64")
    except (TypeError, ValueError):
        return pd.Series(np.nan, index=series.index, dtype="float64")


def clean(values: Any, positive: bool = False) -> pd.Series:
    """Numeric series without NaN and without infinity."""
    series = as_numeric(values).replace([np.inf, -np.inf], np.nan).dropna()
    if positive:
        series = series[series > 0]
    return series


def aligned(x: Any, y: Any) -> tuple[pd.Series, pd.Series]:
    """Aligns two series and drops rows with missing values."""
    left, right = as_numeric(x), as_numeric(y)
    if not left.index.equals(right.index):
        left = left.reset_index(drop=True)
        right = right.reset_index(drop=True)
    frame = pd.DataFrame({"x": left, "y": right})
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
    return frame["x"], frame["y"]


def pearson(x: Any, y: Any) -> float | None:
    a, b = aligned(x, y)
    if len(a) < 3 or a.nunique() < 2 or b.nunique() < 2:
        return None
    value = float(np.corrcoef(a.to_numpy(), b.to_numpy())[0, 1])
    return None if math.isnan(value) else value


def spearman(x: Any, y: Any) -> float | None:
    """Pearson on ranks = Spearman (robust against skewed data and outliers)."""
    a, b = aligned(x, y)
    if len(a) < 3:
        return None
    return pearson(a.rank(), b.rank())


def fisher_ci(r: float | None, n: int) -> tuple[float, float] | None:
    """95% confidence interval for a correlation using Fisher's z transform."""
    if r is None or n < 5 or abs(r) >= 1:
        return None
    z = math.atanh(r)
    se = 1.0 / math.sqrt(n - 3)
    return math.tanh(z - Z95 * se), math.tanh(z + Z95 * se)


def corr_p_value(r: float | None, n: int) -> float | None:
    """Approximate two-tailed p-value (based on Fisher's z)."""
    if r is None or n < 5 or abs(r) >= 1:
        return None
    z = math.atanh(r) * math.sqrt(n - 3)
    return float(math.erfc(abs(z) / math.sqrt(2)))


def strength_fa(r: float | None) -> str:
    """Returns correlation strength in plain language."""
    if r is None:
        return "unknown"
    size = abs(r)
    if size < 0.10:
        return "practically none"
    if size < 0.20:
        return "negligible"
    if size < 0.40:
        return "weak"
    if size < 0.60:
        return "moderate"
    if size < 0.80:
        return "strong"
    return "very strong"


@dataclass
class CorrResult:
    """Full output of a correlation analysis."""

    n: int
    pearson: float | None = None
    spearman: float | None = None
    log_pearson: float | None = None
    ci: tuple[float, float] | None = None
    p_value: float | None = None
    x_label: str = "x"
    y_label: str = "y"

    @property
    def best(self) -> float | None:
        """Primary judgment criterion: Spearman (robust against outliers)."""
        return self.spearman if self.spearman is not None else self.pearson

    @property
    def significant(self) -> bool | None:
        if self.ci is None:
            return None
        low, high = self.ci
        return low > 0 or high < 0

    def direction_fa(self) -> str:
        r = self.best
        if r is None:
            return "unknown"
        if abs(r) < 0.10:
            return "no direction"
        return "direct (both rise together)" if r > 0 else "inverse (one rises, the other falls)"

    def summary_fa(self) -> str:
        if self.best is None:
            return f"Not enough data to assess the relationship between {self.x_label} and {self.y_label} (n={self.n})."
        parts = [
            f"n={self.n:,}",
            f"Spearman={fmt_num(self.spearman)}",
            f"Pearson={fmt_num(self.pearson)}",
        ]
        if self.log_pearson is not None:
            parts.append(f"Pearson(log–log)={fmt_num(self.log_pearson)}")
        if self.ci:
            parts.append(f"CI95=[{fmt_num(self.ci[0])}, {fmt_num(self.ci[1])}]")
        if self.p_value is not None:
            parts.append(f"p≈{self.p_value:.3g}")
        tail = "significant" if self.significant else "not significant (interval includes zero)"
        return (
            f"{self.x_label} × {self.y_label} → relationship is "
            f"{strength_fa(self.best)} and {self.direction_fa()} — {tail}  [{' | '.join(parts)}]"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "pearson": self.pearson,
            "spearman": self.spearman,
            "log_pearson": self.log_pearson,
            "ci95": list(self.ci) if self.ci else None,
            "p_value": self.p_value,
        }


def correlate(
    x: Any,
    y: Any,
    x_label: str = "x",
    y_label: str = "y",
    with_log: bool = True,
) -> CorrResult:
    a, b = aligned(x, y)
    result = CorrResult(n=len(a), x_label=x_label, y_label=y_label)
    if len(a) < 3:
        return result
    result.pearson = pearson(a, b)
    result.spearman = spearman(a, b)
    if with_log and (a >= 0).all() and (b >= 0).all():
        result.log_pearson = pearson(np.log1p(a), np.log1p(b))
    result.ci = fisher_ci(result.best, result.n)
    result.p_value = corr_p_value(result.best, result.n)
    return result


def correlation_matrix(
    frame: pd.DataFrame,
    columns: Sequence[str],
    method: str = "spearman",
    min_pairs: int = 10,
) -> pd.DataFrame:
    """Pairwise correlation matrix (rows with missing values are dropped per pair)."""
    usable = [c for c in columns if c in frame.columns and as_numeric(frame[c]).notna().sum() >= min_pairs]
    out = pd.DataFrame(np.nan, index=usable, columns=usable, dtype="float64")
    func = spearman if method == "spearman" else pearson
    for i, left in enumerate(usable):
        out.loc[left, left] = 1.0
        for right in usable[i + 1 :]:
            value = func(frame[left], frame[right])
            out.loc[left, right] = value
            out.loc[right, left] = value
    return out


# ────────────── two-group comparison ─────────────


def mann_whitney(a: Any, b: Any) -> dict[str, Any] | None:
    """Mann–Whitney U test with normal approximation and tie correction.

    Output includes Cliff's delta: a number between -1 and +1 that says, if we
    take one random sample from each group, how likely the first is larger.
    """
    left, right = clean(a), clean(b)
    n1, n2 = len(left), len(right)
    if n1 < 3 or n2 < 3:
        return None

    combined = pd.concat([left, right], ignore_index=True)
    ranks = combined.rank()
    r1 = float(ranks.iloc[:n1].sum())
    u1 = r1 - n1 * (n1 + 1) / 2
    u2 = n1 * n2 - u1

    total = n1 + n2
    ties = combined.value_counts()
    tie_term = float(((ties**3) - ties).sum())
    variance = (n1 * n2 / 12.0) * ((total + 1) - tie_term / (total * (total - 1)))
    sigma = math.sqrt(variance) if variance > 0 else 0.0
    mu = n1 * n2 / 2.0
    z = (min(u1, u2) - mu) / sigma if sigma else 0.0
    p = float(math.erfc(abs(z) / math.sqrt(2))) if sigma else 1.0

    return {
        "n1": n1,
        "n2": n2,
        "u": min(u1, u2),
        "z": z,
        "p_value": p,
        "cliffs_delta": 2 * u1 / (n1 * n2) - 1,
        "median1": float(left.median()),
        "median2": float(right.median()),
        "mean1": float(left.mean()),
        "mean2": float(right.mean()),
    }


def mann_whitney_fa(test: dict[str, Any] | None, name1: str, name2: str) -> str:
    if not test:
        return f"Not enough data to compare {name1} and {name2}."
    verdict = "the difference is significant" if test["p_value"] < 0.05 else "the difference is not significant"
    delta = test["cliffs_delta"]
    size = abs(delta)
    effect = "negligible" if size < 0.11 else "small" if size < 0.28 else "moderate" if size < 0.43 else "large"
    return (
        f"Median {name1} = {fmt_num(test['median1'])} vs {name2} = {fmt_num(test['median2'])} — "
        f"{verdict} (Mann–Whitney p≈{test['p_value']:.3g}, effect size {effect}, "
        f"Cliff's δ={fmt_num(delta)}, n={test['n1']:,}/{test['n2']:,})"
    )


# ─────────────── concentration and inequality ──────────────


def gini(values: Any) -> float | None:
    """Gini coefficient: 0 = perfectly equal, close to 1 = everything held by a few."""
    series = clean(values)
    series = series[series >= 0]
    if len(series) < 2 or series.sum() <= 0:
        return None
    data = np.sort(series.to_numpy())
    n = data.size
    cumulative = np.cumsum(data)
    return float((n + 1 - 2 * (cumulative / cumulative[-1]).sum()) / n)


def lorenz(values: Any) -> tuple[np.ndarray, np.ndarray] | None:
    """Lorenz curve points (cumulative population share and cumulative value share)."""
    series = clean(values)
    series = series[series >= 0]
    if len(series) < 2 or series.sum() <= 0:
        return None
    data = np.sort(series.to_numpy())
    cumulative = np.cumsum(data) / data.sum()
    x = np.arange(1, data.size + 1) / data.size
    return np.concatenate([[0.0], x]), np.concatenate([[0.0], cumulative])


def top_share(values: Any, fractions: Sequence[float] = (0.01, 0.05, 0.10, 0.20)) -> dict[str, float]:
    """Share of the top 1% / 5% / 10% / 20% of total value."""
    series = clean(values)
    series = series[series >= 0]
    out: dict[str, float] = {}
    if series.empty or series.sum() <= 0:
        return out
    ordered = series.sort_values(ascending=False).to_numpy()
    total = ordered.sum()
    for fraction in fractions:
        take = max(1, int(round(len(ordered) * fraction)))
        out[f"top_{int(fraction * 100)}pct"] = float(ordered[:take].sum() / total)
    return out


def hhi(values: Any) -> float | None:
    """Herfindahl index (market concentration) between 0 and 1."""
    series = clean(values)
    series = series[series >= 0]
    if series.empty or series.sum() <= 0:
        return None
    share = series / series.sum()
    return float((share**2).sum())


# ──────────────── table building ─────────────────


PERCENTILES = (0.25, 0.50, 0.75, 0.90, 0.95, 0.99)


def describe(values: Any) -> dict[str, Any]:
    """Numeric summary of a column (with high percentiles, important for skewed data)."""
    raw = as_numeric(values)
    series = clean(raw)
    out: dict[str, Any] = {
        "count": int(len(series)),
        "missing": int(raw.isna().sum()),
    }
    if series.empty:
        return out
    quantiles = series.quantile(list(PERCENTILES))
    out.update(
        {
            "mean": float(series.mean()),
            "std": float(series.std()) if len(series) > 1 else 0.0,
            "min": float(series.min()),
            "p25": float(quantiles.loc[0.25]),
            "median": float(quantiles.loc[0.50]),
            "p75": float(quantiles.loc[0.75]),
            "p90": float(quantiles.loc[0.90]),
            "p95": float(quantiles.loc[0.95]),
            "p99": float(quantiles.loc[0.99]),
            "max": float(series.max()),
            "zeros": int((series == 0).sum()),
        }
    )
    return out


def describe_table(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    rows = []
    for column in columns:
        if column not in frame.columns:
            continue
        stats = describe(frame[column])
        if not stats.get("count"):
            continue
        rows.append({"column": column, **stats})
    return pd.DataFrame(rows)


def value_counts_table(
    values: Any,
    top: int | None = None,
    dropna: bool = False,
    label: str = "value",
    other_label: str = "Other",
) -> pd.DataFrame:
    """Frequency table + percentage share + cumulative share."""
    series = values if isinstance(values, pd.Series) else pd.Series(list(values))
    counts = series.value_counts(dropna=dropna, sort=True)
    if top is not None and len(counts) > top:
        head = counts.iloc[:top]
        rest = counts.iloc[top:].sum()
        counts = pd.concat([head, pd.Series({other_label: rest})])
    total = counts.sum()
    frame = pd.DataFrame({label: counts.index.astype("object"), "count": counts.to_numpy()})
    frame["share"] = frame["count"] / total if total else np.nan
    frame["cumulative"] = frame["share"].cumsum()
    return frame.reset_index(drop=True)


def ordered_counts_table(series: pd.Series, label: str = "tier") -> pd.DataFrame:
    """For ordered categorical columns (price/size buckets) — natural order is preserved."""
    counts = series.value_counts(dropna=True, sort=False)
    if isinstance(series.dtype, pd.CategoricalDtype):
        counts = counts.reindex(list(series.cat.categories)).fillna(0).astype("int64")
    total = counts.sum()
    frame = pd.DataFrame({label: counts.index.astype("object"), "count": counts.to_numpy()})
    frame["share"] = frame["count"] / total if total else np.nan
    frame["cumulative"] = frame["share"].cumsum()
    return frame.reset_index(drop=True)


AGG_LABELS = {
    "count": "count",
    "median": "median",
    "mean": "mean",
}


def group_summary(
    frame: pd.DataFrame,
    by: str,
    metrics: dict[str, Sequence[str]],
    min_count: int = 1,
    sort_by: str | None = None,
    ascending: bool = False,
    top: int | None = None,
) -> pd.DataFrame:
    """Group summary: {column: [functions]} → flat table.

    Example: group_summary(g, "category_slug", {"total_members": ["count", "median"]})
    """
    if by not in frame.columns:
        return pd.DataFrame()
    usable = frame[frame[by].notna()]
    if usable.empty:
        return pd.DataFrame()

    observed = not isinstance(usable[by].dtype, pd.CategoricalDtype)
    grouped = usable.groupby(by, observed=observed, dropna=True)
    out = pd.DataFrame({"count": grouped.size()})
    for column, functions in metrics.items():
        if column not in usable.columns:
            continue
        numeric = grouped[column]
        for function in functions:
            name = f"{column}_{function}"
            try:
                out[name] = numeric.agg(function)
            except (TypeError, ValueError):
                continue
    out = out[out["count"] >= min_count]
    if sort_by and sort_by in out.columns:
        out = out.sort_values(sort_by, ascending=ascending)
    if top:
        out = out.head(top)
    return out.reset_index()


def share_of(mask: Any) -> float | None:
    """Share of True in a boolean mask (ignoring NaN)."""
    series = pd.Series(mask)
    valid = series.dropna()
    if valid.empty:
        return None
    return float(valid.astype(bool).mean())


def bucket(
    values: Any,
    edges: Sequence[float],
    labels: Sequence[str],
    right: bool = False,
) -> pd.Series:
    """Numeric binning into an ordered category."""
    series = as_numeric(values)
    return pd.cut(series, bins=list(edges), labels=list(labels), right=right, ordered=True)


# ───────────────── formatting ──────────────────


def fmt_num(value: Any, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,}"
    return f"{float(value):,.{digits}f}".rstrip("0").rstrip(".")


def fmt_int(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{int(round(float(value))):,}"


def fmt_pct(value: Any, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{float(value) * 100:.{digits}f}%"


def fmt_money(value: Any, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"${float(value):,.{digits}f}"


def fmt_ratio(numerator: Any, denominator: Any) -> str:
    try:
        if not denominator:
            return "—"
        return fmt_pct(float(numerator) / float(denominator))
    except (TypeError, ValueError, ZeroDivisionError):
        return "—"
