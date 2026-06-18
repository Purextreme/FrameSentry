from __future__ import annotations

from collections.abc import Callable

from ..frame_reader import FrameMetric
from ..utils.timecode import frame_to_timecode


def detect_black_frames(metrics: list[FrameMetric], fps: float) -> list[dict]:
    return _detect_low_detail_runs(
        metrics,
        fps,
        event_type="black_frame",
        predicate=lambda metric: metric.mean_luma < 10 and metric.std_luma < 5 and metric.edge_density < 0.01,
        reason="画面平均亮度、亮度波动和边缘密度都很低，疑似黑帧，建议人工复核。",
    )


def detect_blank_frames(metrics: list[FrameMetric], fps: float) -> list[dict]:
    return _detect_low_detail_runs(
        metrics,
        fps,
        event_type="blank_frame",
        predicate=lambda metric: metric.std_luma < 5 and metric.edge_density < 0.01 and metric.mean_luma >= 10,
        reason="画面亮度波动和边缘密度都很低，疑似灰帧或空画面，建议人工复核。",
    )


def _detect_low_detail_runs(
    metrics: list[FrameMetric],
    fps: float,
    event_type: str,
    predicate: Callable[[FrameMetric], bool],
    reason: str,
) -> list[dict]:
    events: list[dict] = []
    start = None

    for index, metric in enumerate(metrics):
        if predicate(metric):
            if start is None:
                start = index
        elif start is not None:
            events.append(_build_event(event_type, metrics, fps, start, index - 1, reason))
            start = None

    if start is not None:
        events.append(_build_event(event_type, metrics, fps, start, len(metrics) - 1, reason))
    return events


def _build_event(event_type: str, metrics: list[FrameMetric], fps: float, start: int, end: int, reason: str) -> dict:
    start_metric = metrics[start]
    end_metric = metrics[end]
    return {
        "type": event_type,
        "severity": "warning",
        "start_frame": start_metric.frame_index,
        "end_frame": end_metric.frame_index,
        "start_timecode": frame_to_timecode(start_metric.frame_index, fps),
        "end_timecode": frame_to_timecode(end_metric.frame_index, fps),
        "duration_frames": end - start + 1,
        "confidence": 0.8,
        "mean_luma": round(start_metric.mean_luma, 3),
        "std_luma": round(start_metric.std_luma, 3),
        "edge_density": round(start_metric.edge_density, 5),
        "reason": reason,
    }
