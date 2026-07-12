from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from framesentry.analysis import AnalysisRunner, AnalyzerRegistry, BaseAnalyzer, ModuleResult, VideoContext
from framesentry.analyzers.subtitle_analysis import (
    SubtitleAnalysisAnalyzer,
    calculate_pixel_stability,
    mark_persistent_overlays,
    merge_ocr_records,
    sample_and_ocr,
)
from framesentry.config import load_api_config
from framesentry.metadata import VideoMetadata


class ConfigTests(unittest.TestCase):
    def test_missing_config_is_clear(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            missing = Path(temporary_dir) / "missing.json"
            with self.assertRaisesRegex(FileNotFoundError, "API config file not found"):
                load_api_config(missing)

    def test_empty_api_key_is_clear(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "api_config.json"
            path.write_text(json.dumps({"base_url": "https://example.test/v1", "api_key": ""}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "api_key is empty"):
                load_api_config(path)


class FilteringTests(unittest.TestCase):
    def test_stable_text_pixels_are_found_without_blocks(self) -> None:
        frame = np.zeros((180, 320), dtype=np.uint8)
        cv2.putText(frame, "TEXT", (90, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 255, 2)

        metrics, mask = calculate_pixel_stability(frame, frame, frame)

        self.assertTrue(metrics["has_stable_clusters"])
        self.assertGreater(metrics["stable_cluster_pixels"], 20)
        self.assertGreater(np.count_nonzero(mask[120:160]), 0)

    def test_localized_change_uses_next_stable_frame_before_force_interval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            video = Path(temporary_dir) / "localized_change.avi"
            blank = np.zeros((90, 160, 3), dtype=np.uint8)
            with_text = blank.copy()
            cv2.putText(with_text, "TEXT", (45, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            _write_video(video, [blank] * 10 + [with_text] * 30)

            _, stats, _ = sample_and_ocr(video, 10.0, FakeClient())

            candidate_times = [sample["candidate_frame_time"] for sample in stats["samples"] if sample["candidate"]]
            self.assertIn(1.5, candidate_times)

    def test_still_video_does_not_call_ocr_frequently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            video = Path(temporary_dir) / "still.avi"
            _write_video(video, [np.zeros((90, 160, 3), dtype=np.uint8)] * 50)
            client = FakeClient()

            records, stats, warnings = sample_and_ocr(video, 10.0, client)

            self.assertEqual(warnings, [])
            self.assertEqual(stats["sampled_frames"], 10)
            self.assertLessEqual(stats["ocr_api_calls"], 2)
            self.assertEqual(len(records), stats["ocr_candidate_frames"])

    def test_unchanged_scene_is_one_stable_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            video = Path(temporary_dir) / "repeated_text.avi"
            _write_video(video, [np.zeros((90, 160, 3), dtype=np.uint8)] * 100)

            _, stats, _ = sample_and_ocr(video, 10.0, FakeClient())

            candidate_times = [sample["time"] for sample in stats["samples"] if sample["candidate"]]
            self.assertEqual(candidate_times, [0.0, 1.0])

    def test_continuously_changing_video_is_not_a_stable_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            video = Path(temporary_dir) / "changing.avi"
            frames = [np.full((90, 160, 3), index * 4 % 255, dtype=np.uint8) for index in range(100)]
            _write_video(video, frames)
            client = FakeClient()

            _, stats, _ = sample_and_ocr(video, 10.0, client)

            candidate_times = [sample["time"] for sample in stats["samples"] if sample["candidate"]]
            self.assertEqual(candidate_times, [0.0])


class SegmentTests(unittest.TestCase):
    def test_same_ocr_text_merges(self) -> None:
        records = [{"time": 0.0, "text": "Hello world"}, {"time": 1.0, "text": "Hello\nworld"}]
        segments = merge_ocr_records(records)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["source_frame_times"], [0.0, 1.0])

    def test_long_lived_text_is_persistent_overlay(self) -> None:
        segments = [{"text": "LOGO", "start_time": 0.0, "end_time": 20.0, "persistent_overlay": False}]
        mark_persistent_overlays(segments, 30.0)
        self.assertTrue(segments[0]["persistent_overlay"])

    def test_repeated_line_is_marked_without_hiding_dynamic_text(self) -> None:
        disclaimer = "产品外观和界面仅供参考"
        records = [
            {"time": time, "text": f"标题{index}\n{disclaimer}", "response": {"lines": [f"标题{index}", disclaimer]}}
            for index, time in enumerate([0.0, 16.0, 32.0])
        ]
        segments = merge_ocr_records(records)

        overlays = mark_persistent_overlays(segments, 50.0)

        self.assertEqual([item["text"] for item in overlays], [disclaimer])
        self.assertTrue(all(segment["persistent_overlay_lines"] == [disclaimer] for segment in segments))
        self.assertTrue(all(not segment["persistent_overlay"] for segment in segments))


class AnalyzerTests(unittest.TestCase):
    def test_api_failure_does_not_interrupt_other_analyzer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            video = Path(temporary_dir) / "sample.avi"
            _write_video(video, [np.zeros((90, 160, 3), dtype=np.uint8)] * 10)
            context = _context(video, Path(temporary_dir))
            registry = AnalyzerRegistry()
            registry.register(SubtitleAnalysisAnalyzer(FailingClient()))
            registry.register(PassingAnalyzer())

            results = AnalysisRunner(registry).run(context)

            self.assertEqual(results["subtitle_analysis"].status, "completed")
            self.assertTrue(results["subtitle_analysis"].warnings)
            self.assertEqual(results["passing"].status, "completed")

    def test_report_contains_call_traffic_and_latency_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            video = Path(temporary_dir) / "sample.avi"
            _write_video(video, [np.zeros((90, 160, 3), dtype=np.uint8)] * 50)

            result = SubtitleAnalysisAnalyzer(FakeClient()).run(_context(video, Path(temporary_dir)))

            self.assertIn("ocr_api_calls", result.summary)
            self.assertIn("total_uploaded_bytes", result.summary)
            self.assertIn("average_ocr_latency_ms", result.summary)
            self.assertIn("upload_size", result.data["ocr_records"][0])
            self.assertIn("latency_ms", result.data["ocr_records"][0])


class FakeClient:
    def ocr(self, jpeg: bytes) -> dict:
        return {"text": "", "lines": [], "has_text": False}

    def review(self, previous_text: str, current_text: str, next_text: str) -> dict:
        return {"suspected_error": False}


class FailingClient(FakeClient):
    def ocr(self, jpeg: bytes) -> dict:
        raise RuntimeError("mock OCR failure")


class TextThenEmptyClient(FakeClient):
    def __init__(self) -> None:
        self.calls = 0

    def ocr(self, jpeg: bytes) -> dict:
        self.calls += 1
        if self.calls == 1:
            return {"text": "TEXT", "lines": ["TEXT"], "has_text": True}
        return super().ocr(jpeg)


class RepeatedTextClient(FakeClient):
    def ocr(self, jpeg: bytes) -> dict:
        return {"text": "固定文字", "lines": ["固定文字"], "has_text": True}


class PassingAnalyzer(BaseAnalyzer):
    module_id = "passing"
    module_name = "Passing"

    def run(self, context: VideoContext) -> ModuleResult:
        return ModuleResult(module_id=self.module_id, module_name=self.module_name)


def _context(video: Path, output: Path) -> VideoContext:
    metadata = VideoMetadata(width=160, height=90, fps=10.0, duration=5.0, codec="MJPG", frame_count=50, audio_stream_exists=False)
    return VideoContext(video_path=video, output_dir=output, artifact_dir=output, video_id=video.stem, metadata=metadata)


def _write_video(path: Path, frames: list[np.ndarray]) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (160, 90))
    if not writer.isOpened():
        raise RuntimeError("Cannot create test video")
    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()


if __name__ == "__main__":
    unittest.main()
