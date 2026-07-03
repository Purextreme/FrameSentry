from __future__ import annotations

import statistics

from ..frame_reader import FrameMetric
from ..metrics import confidence_from_margin
from ..utils.timecode import frame_to_timecode


PERIODIC_DUPLICATE_REASON = "同一 60 秒窗口内出现多次间断性重复帧，可能存在掉帧或帧率不足，建议人工复核。"


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


def mark_periodic_duplicate_frame_warnings(
    events: list[dict],
    fps: float,
    *,
    window_seconds: int = 60,
    threshold: int = 10,
) -> list[dict]:
    if fps <= 0 or window_seconds <= 0 or threshold < 1:
        return events

    duplicate_events = [
        event
        for event in events
        if event.get("type") == "duplicate_frame" and isinstance(event.get("start_frame"), (int, float))
    ]
    duplicate_events.sort(key=lambda event: float(event["start_frame"]))

    window_frames = fps * window_seconds
    for start_index, start_event in enumerate(duplicate_events):
        start_frame = float(start_event["start_frame"])
        window_events = [
            event
            for event in duplicate_events[start_index:]
            if float(event["start_frame"]) - start_frame <= window_frames
        ]
        if len(window_events) <= threshold:
            continue

        for event in window_events:
            event["pattern_warning"] = True
            event["pattern_window_seconds"] = window_seconds
            event["pattern_duplicate_events"] = max(event.get("pattern_duplicate_events", 0), len(window_events))
            if PERIODIC_DUPLICATE_REASON not in event.get("reason", ""):
                event["reason"] = f"{event.get('reason', '')} {PERIODIC_DUPLICATE_REASON}".strip()

    return events


def _median_diffs(metrics: list[FrameMetric], start: int, end: int) -> float:
    values = [metric.pixel_diff_to_prev for metric in metrics[start:end] if metric.pixel_diff_to_prev is not None]
    return float(statistics.median(values)) if values else 0.0


def _is_low_detail(metric: FrameMetric) -> bool:
    return metric.std_luma < 5 and metric.edge_density < 0.01
