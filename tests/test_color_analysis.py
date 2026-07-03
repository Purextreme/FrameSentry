from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from framesentry.analysis import VideoContext
from framesentry.analyzers.color_analysis import (
    ColorAnalysisAnalyzer,
    _dominant_hsv,
    _sample_frame_indices,
)


class ColorAnalysisTests(unittest.TestCase):
    def test_sample_indices_are_limited_and_dynamic(self) -> None:
        short = _sample_frame_indices(frame_count=24, sample_limit=100)
        long = _sample_frame_indices(frame_count=1000, sample_limit=100)

        self.assertEqual(len(short), 24)
        self.assertLessEqual(len(long), 100)
        self.assertGreater(long[1] - long[0], short[1] - short[0])

    def test_dominant_hsv_detects_pure_red(self) -> None:
        frame = np.full((24, 24, 3), (0, 0, 255), dtype=np.uint8)

        dominant = _dominant_hsv(frame)

        self.assertLessEqual(dominant["hue"], 2)
        self.assertGreater(dominant["saturation"], 99)
        self.assertGreater(dominant["value"], 99)
        self.assertEqual(dominant["hex"], "#ff0000")

    def test_color_analyzer_returns_module_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "colors.mp4"
            write_color_video(video)
            context = VideoContext(
                video_path=video,
                output_dir=root / "report",
                video_id="colors",
                settings={"color_sample_limit": 3},
                metadata=FakeMetadata(frame_count=6),
            )

            result = ColorAnalysisAnalyzer().run(context)
            payload = result.to_dict()

        self.assertEqual(result.module_id, "color_analysis")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.severity, "info")
        self.assertEqual(len(result.events), 0)
        self.assertLessEqual(result.data["sample_count"], 3)
        self.assertIn("hsv_trend", [chart["chart_id"] for chart in result.charts])
        json.dumps(payload)


class FakeMetadata:
    width = 64
    height = 64
    fps = 6.0
    duration = 1.0
    codec = "mp4v"
    audio_stream_exists = False

    def __init__(self, frame_count: int) -> None:
        self.frame_count = frame_count


def write_color_video(path: Path) -> None:
    import cv2

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 6.0, (64, 64))
    try:
        colors = [
            (0, 0, 255),
            (0, 255, 0),
            (255, 0, 0),
            (0, 255, 255),
            (255, 255, 0),
            (255, 0, 255),
        ]
        for color in colors:
            writer.write(np.full((64, 64, 3), color, dtype=np.uint8))
    finally:
        writer.release()


if __name__ == "__main__":
    unittest.main()
