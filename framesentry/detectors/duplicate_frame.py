from __future__ import annotations

import statistics

from ..frame_reader import FrameMetric
from ..metrics import confidence_from_margin
from ..utils.timecode import frame_to_timecode


def detect_duplicate_frames(metrics: list[FrameMetric], fps: float, thresholds: dict[str, float], window: int = 5) -> list[dict]:
    events: list[dict] = []
    low_threshold = thresholds["very_low_diff"]
    motion_threshold = thresholds["motion_threshold"]

    index = 1
    while index < len(metrics):
        diff = metrics[index].pixel_diff_to_prev
        if diff is None or diff >= low_threshold:
            index += 1
            continue

        start = index
        while index + 1 < len(metrics):
            next_diff = metrics[index + 1].pixel_diff_to_prev
            if next_diff is None or next_diff >= low_threshold:
                break
            index += 1
        end = index

        before_motion = _median_diffs(metrics, max(1, start - window), start)
        after_motion = _median_diffs(metrics, end + 1, min(len(metrics), end + 1 + window))
        duration = end - start + 1

        if any(_is_low_detail(metric) for metric in metrics[start : end + 1]):
            index += 1
            continue
        if any((metric.hist_diff_to_prev or 0.0) > 0.3 for metric in metrics[start : end + 1]):
            index += 1
            continue

        if duration <= 2 and (before_motion >= motion_threshold or after_motion >= motion_threshold):
            event_diff = metrics[start].pixel_diff_to_prev or 0.0
            confidence_base = max(before_motion, after_motion)
            events.append(
                {
                    "type": "duplicate_frame",
                    "severity": "warning",
                    "start_frame": metrics[start].frame_index,
                    "end_frame": metrics[end].frame_index,
                    "start_timecode": frame_to_timecode(metrics[start].frame_index, fps),
                    "end_timecode": frame_to_timecode(metrics[end].frame_index, fps),
                    "duration_frames": duration,
                    "confidence": confidence_from_margin(confidence_base, motion_threshold),
                    "diff_to_prev": round(event_diff, 3),
                    "before_motion": round(before_motion, 3),
                    "after_motion": round(after_motion, 3),
                    "reason": "该帧与上一帧差异极低，但前后局部存在明显变化，疑似 1-2 帧重复帧，建议人工复核。",
                }
            )
        index += 1
    return events


def _median_diffs(metrics: list[FrameMetric], start: int, end: int) -> float:
    values = [metric.pixel_diff_to_prev for metric in metrics[start:end] if metric.pixel_diff_to_prev is not None]
    return float(statistics.median(values)) if values else 0.0


def _is_low_detail(metric: FrameMetric) -> bool:
    return metric.std_luma < 5 and metric.edge_density < 0.01
