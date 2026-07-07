from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from framesentry.analysis import BaseAnalyzer, ModuleResult, VideoContext
from framesentry.metadata import read_metadata
from framesentry.utils.timecode import seconds_to_timecode


DEFAULT_MOTION_SAMPLE_LIMIT = 100
MOTION_ANALYSIS_SCALE = 160
MOVING_PIXEL_THRESHOLD = 0.5


class MotionAnalysisAnalyzer(BaseAnalyzer):
    module_id = "motion_analysis"
    module_name = "Motion Analysis"

    def run(self, context: VideoContext) -> ModuleResult:
        metadata = context.metadata or read_metadata(context.video_path)
        context.metadata = metadata
        sample_limit = int(context.settings.get("motion_sample_limit", DEFAULT_MOTION_SAMPLE_LIMIT))
        samples = read_motion_samples(
            context.video_path,
            fps=metadata.fps,
            frame_count=metadata.frame_count,
            sample_limit=sample_limit,
        )
        summary = _build_motion_summary(samples)

        return ModuleResult(
            module_id=self.module_id,
            module_name=self.module_name,
            status="completed",
            severity="info",
            summary=summary,
            charts=_build_charts(),
            data={
                "sample_limit": sample_limit,
                "sample_count": len(samples),
                "samples": samples,
                "summary": summary,
            },
        )


def read_motion_samples(
    video_path: str | Path,
    *,
    fps: float,
    frame_count: int | None,
    sample_limit: int = DEFAULT_MOTION_SAMPLE_LIMIT,
) -> list[dict[str, Any]]:
    try:
        import cv2
    except ModuleNotFoundError as exc:
        raise RuntimeError("OpenCV is required for motion analysis. Install dependencies with `pip install -r requirements.txt`.") from exc

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    effective_fps = fps or float(capture.get(cv2.CAP_PROP_FPS) or 0)
    effective_frame_count = int(frame_count or capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    sample_indices = _sample_pair_indices(effective_frame_count, sample_limit)

    samples: list[dict[str, Any]] = []
    try:
        for frame_index in sample_indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index - 1)
            ok_previous, previous_frame = capture.read()
            ok_current, current_frame = capture.read()
            if not ok_previous or not ok_current:
                continue
            samples.append(
                _analyze_frame_pair(
                    previous_frame,
                    current_frame,
                    frame_index=frame_index,
                    fps=effective_fps,
                )
            )
    finally:
        capture.release()

    return samples


def _sample_pair_indices(frame_count: int, sample_limit: int) -> list[int]:
    if frame_count <= 1 or sample_limit <= 0:
        return []
    pair_count = frame_count - 1
    if pair_count <= sample_limit:
        return list(range(1, frame_count))

    step = (pair_count - 1) / (sample_limit - 1)
    indices = [1 + round(index * step) for index in range(sample_limit)]
    return sorted(set(indices))


def _analyze_frame_pair(previous_frame, current_frame, *, frame_index: int, fps: float) -> dict[str, Any]:
    import cv2
    import numpy as np

    previous_gray = _resize_gray(previous_frame)
    current_gray = _resize_gray(current_frame)
    flow = cv2.calcOpticalFlowFarneback(
        previous_gray,
        current_gray,
        None,
        0.5,
        3,
        15,
        3,
        5,
        1.2,
        0,
    )
    magnitude = np.sqrt(flow[:, :, 0] * flow[:, :, 0] + flow[:, :, 1] * flow[:, :, 1])

    return {
        "frame_index": frame_index,
        "timestamp": round(frame_index / fps, 3) if fps else 0.0,
        "timecode": seconds_to_timecode(frame_index / fps) if fps else "00:00:00",
        "mean_motion_px": round(float(np.mean(magnitude)), 4),
        "p95_motion_px": round(float(np.percentile(magnitude, 95)), 4),
        "moving_area_percent": round(float(np.count_nonzero(magnitude >= MOVING_PIXEL_THRESHOLD) / magnitude.size * 100), 2),
    }


def _resize_gray(frame):
    import cv2

    height, width = frame.shape[:2]
    if width >= height:
        target_width = MOTION_ANALYSIS_SCALE
        target_height = max(1, round(height * (target_width / width)))
    else:
        target_height = MOTION_ANALYSIS_SCALE
        target_width = max(1, round(width * (target_height / height)))
    small = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def _build_motion_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {"sample_count": 0}

    mean_values = [float(sample["mean_motion_px"]) for sample in samples]
    p95_values = [float(sample["p95_motion_px"]) for sample in samples]
    moving_area_values = [float(sample["moving_area_percent"]) for sample in samples]
    average_motion = statistics.fmean(mean_values)
    variability = statistics.pstdev(mean_values) if len(mean_values) > 1 else 0.0

    return {
        "sample_count": len(samples),
        "average_mean_motion_px": round(average_motion, 4),
        "peak_p95_motion_px": round(max(p95_values), 4),
        "average_moving_area_percent": round(statistics.fmean(moving_area_values), 2),
        "motion_variability": round(variability, 4),
        "motion_level": _motion_level(average_motion),
        "rhythm_label": _rhythm_label(mean_values, average_motion, variability),
    }


def _motion_level(average_motion: float) -> str:
    if average_motion < 0.05:
        return "still"
    if average_motion < 0.5:
        return "low"
    if average_motion < 2.0:
        return "medium"
    return "high"


def _rhythm_label(mean_values: list[float], average_motion: float, variability: float) -> str:
    if average_motion < 0.05:
        return "mostly_still"
    if variability < max(0.08, average_motion * 0.25):
        return "steady"
    peak = max(mean_values)
    if peak >= max(1.0, average_motion * 3):
        return "bursty"
    return "variable"


def _build_charts() -> list[dict[str, Any]]:
    return [
        {
            "chart_id": "motion_intensity",
            "title": "运动强度趋势",
            "description": "mean_motion_px 是相邻采样帧之间的平均光流位移；p95_motion_px 是所有像素运动量的第 95 百分位，表示画面中运动较明显区域的运动量。",
            "x_field": "timestamp",
            "series": [
                {"field": "mean_motion_px", "label": "平均运动量", "unit": "pixel"},
                {"field": "p95_motion_px", "label": "P95 运动量", "unit": "pixel"},
            ],
        },
        {
            "chart_id": "moving_area",
            "title": "运动覆盖面积趋势",
            "description": "运动覆盖面积表示光流位移不低于 0.5 像素的缩略图像素占比。",
            "x_field": "timestamp",
            "series": [{"field": "moving_area_percent", "label": "运动覆盖面积", "unit": "percent", "range": [0, 100]}],
        },
    ]
