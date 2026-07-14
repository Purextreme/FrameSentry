from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from framesentry.analysis import AnalysisRunner, AnalyzerRegistry, BaseAnalyzer, ModuleResult, VideoContext
from framesentry.analyzers.llm_subtitle_detection import (
    LlmSubtitleDetectionAnalyzer,
    sample_video,
    validate_detection_response,
)
from framesentry.config import load_api_config
from framesentry.metadata import VideoMetadata


class ConfigTests(unittest.TestCase):
    def test_missing_config_is_clear(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            with self.assertRaisesRegex(FileNotFoundError, "API config file not found"):
                load_api_config(Path(temporary_dir) / "missing.json")

    def test_empty_api_key_is_clear(self) -> None:
        self._assert_invalid_config({"base_url": "https://example.test/v1", "api_key": "", "multimodal_model": "mimo-v2.5"}, "api_key is empty")

    def test_empty_model_is_clear(self) -> None:
        self._assert_invalid_config({"base_url": "https://example.test/v1", "api_key": "secret", "multimodal_model": ""}, "multimodal_model is empty")

    def _assert_invalid_config(self, payload: dict, message: str) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "api_config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, message):
                load_api_config(path)


class SamplingTests(unittest.TestCase):
    def test_samples_one_frame_per_second_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            video = Path(temporary_dir) / "sample.avi"
            _write_video(video, 35, fps=10.0)
            samples = sample_video(video)
            self.assertEqual([item["time"] for item in samples], [0.0, 1.0, 2.0, 3.0])

    def test_sampling_stops_at_sixty_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            video = Path(temporary_dir) / "long.avi"
            _write_video(video, 610, fps=10.0)
            samples = sample_video(video)
            self.assertEqual(len(samples), 60)
            self.assertEqual(samples[-1]["time"], 59.0)


class ResponseTests(unittest.TestCase):
    def test_clamps_times_and_preserves_original_text(self) -> None:
        response = {
            "processed_frame_times": [0.0, 1.0, 2.0],
            "segments": [{"start_time": -1, "end_time": 9, "text": "爻光", "confidence": 1.5}],
        }
        segments, _ = validate_detection_response(response, [0.0, 1.0, 2.0])
        self.assertEqual((segments[0]["start_time"], segments[0]["end_time"]), (0.0, 2.0))
        self.assertEqual(segments[0]["text"], "爻光")
        self.assertEqual(segments[0]["confidence"], 1.0)

    def test_allows_incomplete_processed_frame_times(self) -> None:
        segments, processed_times = validate_detection_response(
            {"processed_frame_times": [0.0], "segments": []}, [0.0, 1.0]
        )
        self.assertEqual(segments, [])
        self.assertEqual(processed_times, [0.0])


class AnalyzerTests(unittest.TestCase):
    def test_video_over_sixty_seconds_is_skipped_without_api_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            video = Path(temporary_dir) / "long.avi"
            _write_video(video, 601, fps=10.0)
            client = CountingClient()
            result = LlmSubtitleDetectionAnalyzer(client).run(_context(video, Path(temporary_dir)))
            self.assertEqual(result.status, "skipped")
            self.assertEqual(client.calls, 0)
            self.assertIn("超过 60 秒", result.warnings[0]["message"])

    def test_api_failure_does_not_interrupt_other_analyzer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            video = Path(temporary_dir) / "sample.avi"
            _write_video(video, 10)
            registry = AnalyzerRegistry()
            registry.register(LlmSubtitleDetectionAnalyzer(FailingClient()))
            registry.register(PassingAnalyzer())
            results = AnalysisRunner(registry).run(_context(video, Path(temporary_dir)))
            self.assertEqual(results["llm_subtitle_detection"].status, "failed")
            self.assertEqual(results["passing"].status, "completed")

    def test_report_contains_metrics_and_suspected_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            video = Path(temporary_dir) / "sample.avi"
            _write_video(video, 20)
            output = Path(temporary_dir) / "中文报告"
            result = LlmSubtitleDetectionAnalyzer(FakeClient()).run(_context(video, output))
            self.assertEqual(result.summary["model_api_calls"], 1)
            self.assertGreater(result.summary["total_uploaded_bytes"], 0)
            self.assertIn("model_latency_ms", result.summary)
            self.assertEqual(result.summary["total_tokens"], 30)
            self.assertEqual(len(result.events), 1)
            self.assertTrue(result.events[0]["reason"].startswith("疑似："))
            self.assertEqual(result.data["processed_frame_times"], [0.0, 1.0])
            self.assertTrue(result.data["segments"][0]["screenshot"])
            self.assertTrue((output / result.data["segments"][0]["screenshot"]).is_file())

    def test_secret_is_not_written_to_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            video = Path(temporary_dir) / "sample.avi"
            _write_video(video, 10)
            result = LlmSubtitleDetectionAnalyzer(FakeClient()).run(_context(video, Path(temporary_dir)))
            self.assertNotIn("secret", json.dumps(result.to_dict(), ensure_ascii=False))

    def test_incomplete_processed_times_add_warning_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            video = Path(temporary_dir) / "sample.avi"
            _write_video(video, 20)
            result = LlmSubtitleDetectionAnalyzer(IncompleteTimesClient()).run(
                _context(video, Path(temporary_dir))
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.summary["missing_processed_frames"], 1)
            self.assertEqual(result.data["missing_processed_frame_times"], [1.0])
            self.assertIn("可能不完整", result.warnings[0]["message"])


class FakeClient:
    def detect(self, samples: list[dict]) -> dict:
        times = [item["time"] for item in samples]
        return {
            "processed_frame_times": times,
            "segments": [{
                "start_time": times[0], "end_time": times[-1], "text": "错别字",
                "suspected_error": True, "error_type": "typo", "reason": "用字可疑",
                "suggestion": "请人工复核", "severity": "low", "confidence": 0.8,
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            "model": "mimo-v2.5",
        }


class FailingClient:
    def detect(self, samples: list[dict]) -> dict:
        raise RuntimeError("mock API failure")


class IncompleteTimesClient:
    def detect(self, samples: list[dict]) -> dict:
        return {
            "processed_frame_times": [samples[0]["time"]],
            "segments": [],
            "model": "mimo-v2.5",
        }


class CountingClient:
    def __init__(self) -> None:
        self.calls = 0

    def detect(self, samples: list[dict]) -> dict:
        self.calls += 1
        return {"processed_frame_times": [], "segments": []}


class PassingAnalyzer(BaseAnalyzer):
    module_id = "passing"
    module_name = "Passing"

    def run(self, context: VideoContext) -> ModuleResult:
        return ModuleResult(module_id=self.module_id, module_name=self.module_name)


def _context(video: Path, output: Path) -> VideoContext:
    metadata = VideoMetadata(width=160, height=90, fps=10.0, duration=2.0, codec="MJPG", frame_count=20, audio_stream_exists=False)
    return VideoContext(video_path=video, output_dir=output, artifact_dir=output, video_id=video.stem, metadata=metadata)


def _write_video(path: Path, frame_count: int, fps: float = 10.0) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (160, 90))
    if not writer.isOpened():
        raise RuntimeError("Cannot create test video")
    try:
        for index in range(frame_count):
            writer.write(np.full((90, 160, 3), index % 255, dtype=np.uint8))
    finally:
        writer.release()


if __name__ == "__main__":
    unittest.main()
