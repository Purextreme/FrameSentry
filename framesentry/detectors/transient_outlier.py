from __future__ import annotations

import statistics

from ..frame_reader import FrameMetric
from ..metrics import confidence_from_margin
from ..utils.timecode import frame_to_timecode


def detect_transient_outliers(
    metrics: list[FrameMetric],
    fps: float,
    thresholds: dict[str, float],
    max_outlier_frames: int = 2,
    window: int = 5,
) -> list[dict]:
    events: list[dict] = []
    high_diff = thresholds["high_diff"]
    stability_threshold = thresholds["stability_threshold"]
    coverage_threshold = 0.55
    hist_threshold = 0.35

    index = 1
    while index < len(metrics) - 1:
        incoming = metrics[index].pixel_diff_to_prev or 0.0
        if incoming < high_diff:
            index += 1
            continue

        start = index
        matched = False
        for duration in range(1, max_outlier_frames + 1):
            end = start + duration - 1
            exit_index = end + 1
            if exit_index >= len(metrics):
                break

            internal_diffs = [
                metrics[inner].pixel_diff_to_prev or 0.0
                for inner in range(start + 1, end + 1)
            ]
            if any(diff >= high_diff for diff in internal_diffs):
                continue

            outgoing = metrics[exit_index].pixel_diff_to_prev or 0.0
            incoming_coverage = metrics[start].block_change_ratio_to_prev or 0.0
            outgoing_coverage = metrics[exit_index].block_change_ratio_to_prev or 0.0
            incoming_hist = metrics[start].hist_diff_to_prev or 0.0
            outgoing_hist = metrics[exit_index].hist_diff_to_prev or 0.0
            left_stability = _median_diffs(metrics, max(1, start - window), start)
            right_stability = _median_diffs(metrics, exit_index + 1, min(len(metrics), exit_index + 1 + window))
            side_is_stable = left_stability < stability_threshold or right_stability < stability_threshold
            global_change = incoming_coverage >= coverage_threshold and outgoing_coverage >= coverage_threshold
            color_change = incoming_hist >= hist_threshold and outgoing_hist >= hist_threshold

            if outgoing >= high_diff and side_is_stable and global_change and color_change:
                confidence_source = min(incoming, outgoing)
                confidence = confidence_from_margin(confidence_source, high_diff)
                confidence = round(min(0.99, confidence + min(incoming_coverage, outgoing_coverage) * 0.12), 2)
                events.append(
                    {
                        "type": "transient_outlier",
                        "severity": "warning",
                        "start_frame": metrics[start].frame_index,
                        "end_frame": metrics[end].frame_index,
                        "start_timecode": frame_to_timecode(metrics[start].frame_index, fps),
                        "end_timecode": frame_to_timecode(metrics[end].frame_index, fps),
                        "duration_frames": duration,
                        "confidence": confidence,
                        "incoming_diff": round(incoming, 3),
                        "outgoing_diff": round(outgoing, 3),
                        "incoming_hist_diff": round(incoming_hist, 3),
                        "outgoing_hist_diff": round(outgoing_hist, 3),
                        "incoming_change_coverage": round(incoming_coverage, 3),
                        "outgoing_change_coverage": round(outgoing_coverage, 3),
                        "left_stability": round(left_stability, 3),
                        "right_stability": round(right_stability, 3),
                        "reason": "该短片段与前后局部画面差异均很高，变化覆盖整幅画面且色彩分布明显不同，疑似瞬时异常帧或剪辑残留帧，建议人工复核。",
                    }
                )
                index = exit_index + 1
                matched = True
                break

        if matched:
            continue

        index += 1
    return events


def _median_diffs(metrics: list[FrameMetric], start: int, end: int) -> float:
    values = [metric.pixel_diff_to_prev for metric in metrics[start:end] if metric.pixel_diff_to_prev is not None]
    return float(statistics.median(values)) if values else 0.0
