from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from framesentry.analysis import VideoContext
from framesentry.analyzers.motion_analysis import (
    MotionAnalysisAnalyzer,
    _sample_pair_indices,
    read_motion_samples,
)


class MotionAnalysisTests(unittest.TestCase):
    def test_sample_pair_indices_are_limited_and_start_at_second_frame(self) -> None:
        short = _sample_pair_indices(frame_count=5, sample_limit=100)
        long = _sample_pair_indices(frame_count=1000, sample_limit=100)

        self.assertEqual(short, [1, 2, 3, 4])
        self.assertLessEqual(len(long), 100)
        self.assertEqual(long[0], 1)
        self.assertEqual(long[-1], 999)

    def test_static_video_has_near_zero_motion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "static.mp4"
            write_static_video(video)

            samples = read_motion_samples(video, fps=6.0, frame_count=8, sample_limit=8)

        self.assertTrue(samples)
        self.assertLess(max(sample["mean_motion_px"] for sample in samples), 0.02)
        self.assertLess(max(sample["moving_area_percent"] for sample in samples), 1.0)
        self.assertIn("timecode", samples[0])
        self.assertNotIn("horizontal_motion_px", samples[0])
        self.assertNotIn("vertical_motion_px", samples[0])

    def test_moving_video_has_more_motion_than_static_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            static_video = root / "static.mp4"
            moving_video = root / "moving.mp4"
            write_static_video(static_video)
            write_moving_square_video(moving_video)

            static_samples = read_motion_samples(static_video, fps=6.0, frame_count=8, sample_limit=8)
            moving_samples = read_motion_samples(moving_video, fps=6.0, frame_count=8, sample_limit=8)

        static_average = average(sample["mean_motion_px"] for sample in static_samples)
        moving_average = average(sample["mean_motion_px"] for sample in moving_samples)

        self.assertGreater(moving_average, static_average + 0.05)
        self.assertGreater(max(sample["moving_area_percent"] for sample in moving_samples), 1.0)

    def test_motion_analyzer_returns_module_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "moving.mp4"
            write_moving_square_video(video)
            context = VideoContext(
                video_path=video,
                output_dir=root / "report",
                video_id="moving",
                settings={"motion_sample_limit": 4},
                metadata=FakeMetadata(frame_count=8),
            )

            result = MotionAnalysisAnalyzer().run(context)
            payload = result.to_dict()

        self.assertEqual(result.module_id, "motion_analysis")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.severity, "info")
        self.assertEqual(len(result.events), 0)
        self.assertLessEqual(result.data["sample_count"], 4)
        self.assertIn("motion_intensity", [chart["chart_id"] for chart in result.charts])
        self.assertNotIn("motion_direction", [chart["chart_id"] for chart in result.charts])
        motion_chart = next(chart for chart in result.charts if chart["chart_id"] == "motion_intensity")
        self.assertEqual(motion_chart["x_field"], "timestamp")
        self.assertIn("average_mean_motion_px", result.data["summary"])
        self.assertIn("rhythm_label", result.data["summary"])
        json.dumps(payload)


class FakeMetadata:
    width = 64
    height = 64
    fps = 6.0
    duration = 1.333
    codec = "mp4v"
    audio_stream_exists = False

    def __init__(self, frame_count: int) -> None:
        self.frame_count = frame_count


def write_static_video(path: Path) -> None:
    import cv2

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 6.0, (64, 64))
    try:
        frame = np.full((64, 64, 3), 32, dtype=np.uint8)
        for _index in range(8):
            writer.write(frame)
    finally:
        writer.release()


def write_moving_square_video(path: Path) -> None:
    import cv2

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 6.0, (64, 64))
    try:
        for index in range(8):
            frame = np.zeros((64, 64, 3), dtype=np.uint8)
            x0 = 4 + index * 4
            frame[18:46, x0 : x0 + 28] = 255
            writer.write(frame)
    finally:
        writer.release()


def average(values) -> float:
    values = list(values)
    return sum(values) / len(values)


if __name__ == "__main__":
    unittest.main()
