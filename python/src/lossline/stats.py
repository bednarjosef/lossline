"""Compact numeric summaries of metric histories, for humans and LLM agents."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

SPARK = "▁▂▃▄▅▆▇█"
FLAT_PCT = 1.0  # |change| below this percent is reported as flat

_LOWER_BETTER = ("loss", "error", "err", "perplexity", "ppl", "mse", "mae", "rmse", "wer",
                 "cer", "nll", "regret", "latency", "time")
_HIGHER_BETTER = ("acc", "accuracy", "score", "reward", "return", "f1", "auc", "bleu",
                  "rouge", "precision", "recall", "iou", "map", "win", "success")


def direction(metric: str) -> int:
    """-1 if lower is better, +1 if higher is better, 0 if unknown (by name)."""
    words = metric.lower().replace("-", "_").replace("/", "_").replace(".", "_").split("_")
    if any(w in _LOWER_BETTER for w in words):
        return -1
    if any(w in _HIGHER_BETTER for w in words):
        return 1
    return 0


def metric_stats(points: Sequence[tuple[int, float | None]]) -> dict[str, Any]:
    """last, min/max with their steps, mean of the last 10%, trend over the last 20%."""
    finite = [(s, v) for s, v in points if v is not None and math.isfinite(v)]
    out: dict[str, Any] = {"n": len(points), "last": points[-1][1] if points else None,
                           "last_step": points[-1][0] if points else None}
    if not finite:
        return out
    min_step, min_value = min(finite, key=lambda p: p[1])
    max_step, max_value = max(finite, key=lambda p: p[1])
    tail10 = finite[-max(1, len(finite) // 10):]
    out.update(
        min=min_value, min_step=min_step, max=max_value, max_step=max_step,
        mean_last10=sum(v for _, v in tail10) / len(tail10),
        trend_last20=trend_pct(finite[-max(3, len(finite) // 5):]),
    )
    return out


def trend_pct(points: Sequence[tuple[int, float]]) -> float | None:
    """Percent change across the window along a least-squares line fit.

    Relative to the fitted start value (or the mean |value| if that is ~0).
    """
    if len(points) < 3:
        return None
    xs = [float(s) for s, _ in points]
    ys = [v for _, v in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / var
    start = my + slope * (xs[0] - mx)
    scale = abs(start) if abs(start) > 1e-12 else sum(abs(y) for y in ys) / len(ys)
    if scale == 0:
        return None
    return 100.0 * slope * (xs[-1] - xs[0]) / scale


def trend_arrow(pct: float | None) -> str:
    if pct is None:
        return ""
    if abs(pct) < FLAT_PCT:
        return "→ flat"
    return f"{'↑' if pct > 0 else '↓'}{abs(pct):.{1 if abs(pct) < 100 else 0}f}%"


def sparkline(points: Sequence[tuple[int, float | None]], width: int = 16) -> str:
    """Bucket the history into ``width`` bins by position and draw the bin means."""
    values = [v for _, v in points if v is not None and math.isfinite(v)]
    if not values:
        return ""
    bins = min(width, len(values))
    means = []
    for i in range(bins):
        chunk = values[i * len(values) // bins:(i + 1) * len(values) // bins]
        means.append(sum(chunk) / len(chunk))
    lo, hi = min(means), max(means)
    if hi == lo:
        return SPARK[3] * bins
    return "".join(SPARK[min(7, int((m - lo) / (hi - lo) * 8))] for m in means)


def fmt(value: Any) -> str:
    """Short human number: 4 significant digits, no noise."""
    if value is None:
        return "-"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, int) or (value.is_integer() and abs(value) < 1e6):
        return f"{int(value):d}" if abs(value) < 1e6 else f"{value:.3g}"
    a = abs(value)
    if a != 0 and (a < 1e-3 or a >= 1e6):
        return f"{value:.3g}"
    if a >= 1000:
        return f"{value:.0f}"
    return f"{value:.4g}"
