from __future__ import annotations

import statistics


def median_abs_deviation(values: list[float]) -> float:
    if not values:
        return 0.0
    median = statistics.median(values)
    return statistics.median(abs(value - median) for value in values)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def adaptive_thresholds(diffs: list[float]) -> dict[str, float]:
    clean = [value for value in diffs if value is not None]
    median_diff = statistics.median(clean) if clean else 0.0
    mad_diff = median_abs_deviation(clean)
    p90 = percentile(clean, 0.90)
    p95 = percentile(clean, 0.95)
    p99 = percentile(clean, 0.99)
    p75 = percentile(clean, 0.75)
    robust_high = median_diff + 6 * mad_diff if mad_diff else median_diff + 16
    robust_very_high = median_diff + 10 * mad_diff if mad_diff else median_diff + 26
    robust_motion = median_diff * 0.75 if median_diff else 0.0

    return {
        "median_diff": median_diff,
        "mad_diff": mad_diff,
        "p75_diff": p75,
        "p90_diff": p90,
        "p95_diff": p95,
        "p99_diff": p99,
        "very_low_diff": max(1.0, min(2.0, median_diff * 0.25)),
        "motion_threshold": max(4.0, robust_motion),
        "high_diff": max(18.0, min(p95, robust_high)),
        "very_high_diff": max(28.0, min(p99, robust_very_high)),
        "stability_threshold": max(6.0, median_diff + 2 * mad_diff),
    }


def confidence_from_margin(value: float, threshold: float, scale: float = 2.0) -> float:
    if threshold <= 0:
        return 0.5
    margin = max(0.0, (value - threshold) / (threshold * scale))
    return round(min(0.99, 0.55 + margin), 2)
