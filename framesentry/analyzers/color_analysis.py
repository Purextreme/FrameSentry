from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from framesentry.analysis import BaseAnalyzer, ModuleResult, VideoContext
from framesentry.metadata import read_metadata


DEFAULT_COLOR_SAMPLE_LIMIT = 100
COLOR_ANALYSIS_SCALE = 160
KMEANS_CLUSTER_COUNT = 3
MAX_CLUSTER_PIXELS = 4096


class ColorAnalysisAnalyzer(BaseAnalyzer):
    module_id = "color_analysis"
    module_name = "Color Analysis"

    def run(self, context: VideoContext) -> ModuleResult:
        metadata = context.metadata or read_metadata(context.video_path)
        context.metadata = metadata
        sample_limit = int(context.settings.get("color_sample_limit", DEFAULT_COLOR_SAMPLE_LIMIT))
        samples = read_color_samples(
            context.video_path,
            fps=metadata.fps,
            frame_count=metadata.frame_count,
            sample_limit=sample_limit,
        )

        return ModuleResult(
            module_id=self.module_id,
            module_name=self.module_name,
            status="completed",
            severity="info",
            charts=_build_charts(),
            data={
                "sample_limit": sample_limit,
                "sample_count": len(samples),
                "samples": samples,
                "summary": _build_color_summary(samples),
            },
        )


def read_color_samples(
    video_path: str | Path,
    *,
    fps: float,
    frame_count: int | None,
    sample_limit: int = DEFAULT_COLOR_SAMPLE_LIMIT,
) -> list[dict[str, Any]]:
    try:
        import cv2
    except ModuleNotFoundError as exc:
        raise RuntimeError("OpenCV is required for color analysis. Install dependencies with `pip install -r requirements.txt`.") from exc

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    effective_fps = fps or float(capture.get(cv2.CAP_PROP_FPS) or 0)
    effective_frame_count = int(frame_count or capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    sample_indices = _sample_frame_indices(effective_frame_count, sample_limit)

    samples: list[dict[str, Any]] = []
    try:
        for frame_index in sample_indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                continue
            samples.append(_analyze_frame(frame, frame_index=frame_index, fps=effective_fps))
    finally:
        capture.release()

    return samples


def _sample_frame_indices(frame_count: int, sample_limit: int) -> list[int]:
    if frame_count <= 0 or sample_limit <= 0:
        return []
    if sample_limit == 1:
        return [0]
    if frame_count <= sample_limit:
        return list(range(frame_count))

    step = (frame_count - 1) / (sample_limit - 1)
    indices = [round(index * step) for index in range(sample_limit)]
    return sorted(set(indices))


def _analyze_frame(frame, *, frame_index: int, fps: float) -> dict[str, Any]:
    import cv2
    import numpy as np

    small = _resize_for_color_analysis(frame)
    dominant = _dominant_hsv(small)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    bgr_float = small.reshape(-1, 3).astype("float32")

    brightness_dispersion = float(np.std(gray) / 255 * 100)
    contrast_score = float((np.percentile(gray, 95) - np.percentile(gray, 5)) / 255 * 100)
    color_dispersion = float(np.mean(np.std(bgr_float, axis=0)) / 255 * 100)
    warmth_score = _warmth_score(small)

    return {
        "frame_index": frame_index,
        "timestamp": round(frame_index / fps, 3) if fps else 0.0,
        "dominant_hue": round(dominant["hue"], 2),
        "dominant_saturation": round(dominant["saturation"], 2),
        "dominant_value": round(dominant["value"], 2),
        "dominant_color_bgr": dominant["bgr"],
        "dominant_color_hex": dominant["hex"],
        "dominant_coverage": round(dominant["coverage"], 3),
        "color_dispersion": round(color_dispersion, 2),
        "brightness_dispersion": round(brightness_dispersion, 2),
        "contrast_score": round(contrast_score, 2),
        "warmth_score": round(warmth_score, 2),
        "mean_saturation": round(float(np.mean(hsv[:, :, 1]) / 255 * 100), 2),
        "mean_value": round(float(np.mean(hsv[:, :, 2]) / 255 * 100), 2),
    }


def _resize_for_color_analysis(frame):
    import cv2

    height, width = frame.shape[:2]
    if width >= height:
        target_width = COLOR_ANALYSIS_SCALE
        target_height = max(1, round(height * (target_width / width)))
    else:
        target_height = COLOR_ANALYSIS_SCALE
        target_width = max(1, round(width * (target_height / height)))
    return cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)


def _dominant_hsv(frame) -> dict[str, Any]:
    import cv2
    import numpy as np

    pixels = frame.reshape(-1, 3)
    if len(pixels) > MAX_CLUSTER_PIXELS:
        step = math.ceil(len(pixels) / MAX_CLUSTER_PIXELS)
        pixels = pixels[::step]

    cluster_count = min(KMEANS_CLUSTER_COUNT, len(pixels))
    samples = pixels.astype("float32")
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _compactness, labels, centers = cv2.kmeans(samples, cluster_count, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=cluster_count)
    dominant_index = int(np.argmax(counts))
    dominant_bgr = np.clip(centers[dominant_index], 0, 255).astype("uint8")
    dominant_hsv = cv2.cvtColor(np.array([[dominant_bgr]], dtype="uint8"), cv2.COLOR_BGR2HSV)[0][0]
    b, g, r = [int(value) for value in dominant_bgr]

    return {
        "hue": float(dominant_hsv[0]) * 2,
        "saturation": float(dominant_hsv[1]) / 255 * 100,
        "value": float(dominant_hsv[2]) / 255 * 100,
        "bgr": [b, g, r],
        "hex": f"#{r:02x}{g:02x}{b:02x}",
        "coverage": float(counts[dominant_index] / counts.sum()) if counts.sum() else 0.0,
    }


def _warmth_score(frame) -> float:
    import numpy as np

    bgr = frame.reshape(-1, 3).astype("float32")
    blue = float(np.mean(bgr[:, 0]))
    red = float(np.mean(bgr[:, 2]))
    return max(-100.0, min(100.0, (red - blue) / 255 * 100))


def _build_color_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {
            "sample_count": 0,
        }

    return {
        "sample_count": len(samples),
        "average_hue": round(_circular_hue_mean([sample["dominant_hue"] for sample in samples]), 2),
        "average_saturation": round(_average(samples, "dominant_saturation"), 2),
        "average_value": round(_average(samples, "dominant_value"), 2),
        "average_color_dispersion": round(_average(samples, "color_dispersion"), 2),
        "average_brightness_dispersion": round(_average(samples, "brightness_dispersion"), 2),
        "average_contrast": round(_average(samples, "contrast_score"), 2),
        "average_warmth": round(_average(samples, "warmth_score"), 2),
    }


def _average(samples: list[dict[str, Any]], key: str) -> float:
    return sum(float(sample[key]) for sample in samples) / len(samples)


def _circular_hue_mean(values: list[float]) -> float:
    radians = [math.radians(value) for value in values]
    sin_mean = sum(math.sin(value) for value in radians) / len(radians)
    cos_mean = sum(math.cos(value) for value in radians) / len(radians)
    return math.degrees(math.atan2(sin_mean, cos_mean)) % 360


def _build_charts() -> list[dict[str, Any]]:
    return [
        {
            "chart_id": "hsv_trend",
            "title": "HSV 主色趋势",
            "x_field": "frame_index",
            "series": [
                {"field": "dominant_hue", "label": "H 色相"},
                {"field": "dominant_saturation", "label": "S 饱和度"},
                {"field": "dominant_value", "label": "V 亮度"},
            ],
        },
        {
            "chart_id": "color_dispersion",
            "title": "色彩离散度趋势",
            "x_field": "frame_index",
            "series": [{"field": "color_dispersion", "label": "色彩离散度"}],
        },
        {
            "chart_id": "brightness_contrast",
            "title": "亮度 / 对比度趋势",
            "x_field": "frame_index",
            "series": [
                {"field": "brightness_dispersion", "label": "亮度离散度"},
                {"field": "contrast_score", "label": "对比度"},
            ],
        },
        {
            "chart_id": "warmth",
            "title": "冷暖倾向趋势",
            "x_field": "frame_index",
            "series": [{"field": "warmth_score", "label": "冷暖倾向"}],
        },
    ]
