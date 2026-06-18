from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FrameMetric:
    frame_index: int
    timestamp: float
    mean_luma: float
    std_luma: float
    edge_density: float
    pixel_diff_to_prev: float | None
    hist_diff_to_prev: float | None
    block_mean_diff_to_prev: float | None
    block_change_ratio_to_prev: float | None


def read_frame_metrics(path: Path, sample_scale: int, fps: float) -> list[FrameMetric]:
    try:
        import cv2
    except ModuleNotFoundError as exc:
        raise RuntimeError("OpenCV is required for video scanning. Install dependencies with `pip install -r requirements.txt`.") from exc

    import numpy as np

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {path}")

    metrics: list[FrameMetric] = []
    previous_gray = None
    previous_hist = None
    frame_index = 0
    effective_fps = fps or float(capture.get(cv2.CAP_PROP_FPS) or 0)

    while True:
        ok, frame = capture.read()
        if not ok:
            break

        small = _resize_for_analysis(frame, sample_scale)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        mean_luma = float(np.mean(gray))
        std_luma = float(np.std(gray))
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(np.count_nonzero(edges) / edges.size)
        hist = cv2.calcHist([small], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
        cv2.normalize(hist, hist)

        if previous_gray is None:
            pixel_diff = None
            hist_diff = None
            block_mean_diff = None
            block_change_ratio = None
        else:
            pixel_diff = float(np.mean(cv2.absdiff(gray, previous_gray)))
            hist_diff = float(cv2.compareHist(previous_hist, hist, cv2.HISTCMP_BHATTACHARYYA))
            block_diffs = _block_diffs(gray, previous_gray)
            block_mean_diff = float(np.mean(block_diffs))
            block_change_ratio = float(np.count_nonzero(block_diffs >= max(6.0, pixel_diff * 0.5)) / block_diffs.size)

        metrics.append(
            FrameMetric(
                frame_index=frame_index,
                timestamp=frame_index / effective_fps if effective_fps else 0.0,
                mean_luma=mean_luma,
                std_luma=std_luma,
                edge_density=edge_density,
                pixel_diff_to_prev=pixel_diff,
                hist_diff_to_prev=hist_diff,
                block_mean_diff_to_prev=block_mean_diff,
                block_change_ratio_to_prev=block_change_ratio,
            )
        )
        previous_gray = gray
        previous_hist = hist
        frame_index += 1

    capture.release()
    return metrics


def _resize_for_analysis(frame, sample_scale: int):
    import cv2

    height, width = frame.shape[:2]
    if width >= height:
        target_width = sample_scale
        target_height = max(1, round(height * (target_width / width)))
    else:
        target_height = sample_scale
        target_width = max(1, round(width * (target_height / height)))
    return cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)


def _block_diffs(gray, previous_gray, grid_size: int = 4):
    import numpy as np

    height, width = gray.shape[:2]
    diffs = []
    for row in range(grid_size):
        y0 = round(row * height / grid_size)
        y1 = round((row + 1) * height / grid_size)
        for col in range(grid_size):
            x0 = round(col * width / grid_size)
            x1 = round((col + 1) * width / grid_size)
            current_block = gray[y0:y1, x0:x1]
            previous_block = previous_gray[y0:y1, x0:x1]
            diffs.append(float(np.mean(np.abs(current_block.astype("float32") - previous_block.astype("float32")))))
    return np.array(diffs, dtype="float32")
