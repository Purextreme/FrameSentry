from __future__ import annotations

import json
import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from framesentry.analysis import AnalysisRunner, AnalyzerRegistry, BaseAnalyzer, ModuleResult, ReportBuilder, VideoContext
from framesentry.analyzers.frame_issues import FrameIssueAnalyzer
from framesentry.analyzers.metadata import MetadataAnalyzer
from framesentry.frame_reader import FrameMetric


class AnalysisCoreTests(unittest.TestCase):
    def test_module_result_is_json_serializable(self) -> None:
        result = ModuleResult(
            module_id="frame_issues",
            module_name="Frame Issues",
            assets=[Path("screenshots/frame.jpg")],
        )

        payload = result.to_dict()

        self.assertEqual(payload["assets"], ["screenshots/frame.jpg"])
        json.dumps(payload)

    def test_video_context_creates_path_fields(self) -> None:
        context = VideoContext(video_path="input.mp4", output_dir="output/report", video_id="input")

        self.assertIsInstance(context.video_path, Path)
        self.assertIsInstance(context.output_dir, Path)
        self.assertEqual(context.cache_dir, Path("output/report/cache"))
        self.assertEqual(context.artifact_dir, Path("output/report"))

    def test_runner_continues_when_one_analyzer_fails(self) -> None:
        registry = AnalyzerRegistry()
        registry.register(FailingAnalyzer())
        registry.register(PassingAnalyzer())
        context = VideoContext(video_path="input.mp4", output_dir="output/report", video_id="input")

        results = AnalysisRunner(registry).run(context)

        self.assertEqual(results["broken"].status, "failed")
        self.assertEqual(results["ok"].status, "completed")

    def test_report_builder_uses_module_schema(self) -> None:
        context = VideoContext(
            video_path="input.mp4",
            output_dir="output/report",
            video_id="input",
            settings={
                "source_file": {"path": "input.mp4"},
                "analysis_options": {"sample_scale": 480, "max_outlier_frames": 2, "save_screenshots": True},
            },
        )
        modules = {
            "metadata": ModuleResult(
                module_id="metadata",
                module_name="Metadata",
                data={"video": {"path": "input.mp4", "fps": 25.0}},
            ),
            "frame_issues": ModuleResult(
                module_id="frame_issues",
                module_name="Frame Issues",
                events=[{"type": "black_frame", "start_frame": 1}],
                data={"thresholds": {"high_diff": 18.0}},
            ),
        }

        report = ReportBuilder().build(context, modules)

        self.assertIn("modules", report)
        self.assertIn("metadata", report["modules"])
        self.assertEqual(report["modules"]["frame_issues"]["events"][0]["type"], "black_frame")
        self.assertEqual(report["modules"]["frame_issues"]["data"]["thresholds"], {"high_diff": 18.0})
        self.assertEqual(report["modules"]["metadata"]["data"]["source_file"], {"path": "input.mp4"})
        self.assertEqual(
            report["modules"]["frame_issues"]["data"]["analysis_options"],
            {"sample_scale": 480, "max_outlier_frames": 2, "save_screenshots": True},
        )
        self.assertNotIn("events", report)
        self.assertNotIn("thresholds", report)
        self.assertNotIn("source_file", report)
        self.assertNotIn("analysis_options", report)


class AnalyzerReturnTests(unittest.TestCase):
    def test_metadata_analyzer_returns_module_result(self) -> None:
        context = VideoContext(
            video_path="sample.mp4",
            output_dir="report",
            video_id="sample",
            settings={"fps_normal": {25.0}},
        )
        with patch("framesentry.analyzers.metadata.read_metadata", return_value=FakeMetadata()):
            result = MetadataAnalyzer().run(context)

        self.assertEqual(result.module_id, "metadata")
        self.assertEqual(result.status, "completed")
        self.assertIn("video", result.data)

    def test_frame_issue_analyzer_returns_module_result(self) -> None:
        context = VideoContext(
            video_path="sample.mp4",
            output_dir="report",
            video_id="sample",
            settings={"sample_scale": 160, "max_outlier_frames": 2},
            metadata=FakeMetadata(),
        )
        with patch("framesentry.analyzers.frame_issues.read_frame_metrics", return_value=fake_frame_metrics()):
            result = FrameIssueAnalyzer().run(context)

        self.assertEqual(result.module_id, "frame_issues")
        self.assertEqual(result.status, "completed")
        self.assertIn("thresholds", result.data)

    def test_frame_issue_analyzer_marks_periodic_duplicate_warning(self) -> None:
        context = VideoContext(
            video_path="sample.mp4",
            output_dir="report",
            video_id="sample",
            settings={"sample_scale": 160, "max_outlier_frames": 2},
            metadata=FakeMetadata(),
        )
        with (
            patch("framesentry.analyzers.frame_issues.read_frame_metrics", return_value=fake_frame_metrics()),
            patch("framesentry.analyzers.frame_issues.detect_black_frames", return_value=[]),
            patch("framesentry.analyzers.frame_issues.detect_blank_frames", return_value=[]),
            patch("framesentry.analyzers.frame_issues.detect_transient_outliers", return_value=[]),
            patch("framesentry.analyzers.frame_issues.detect_duplicate_frames", return_value=duplicate_events_for_pattern()),
            patch("framesentry.analyzers.frame_issues.save_event_screenshots"),
        ):
            result = FrameIssueAnalyzer().run(context)

        self.assertEqual(len(result.events), 11)
        self.assertTrue(all(event.get("pattern_warning") for event in result.events))
        self.assertIn("可能存在掉帧或帧率不足", result.events[0]["reason"])


class StreamlitReportTests(unittest.TestCase):
    def test_render_report_accepts_module_report_shape(self) -> None:
        report = {
            "video": {},
            "summary": {"metadata_warnings": 0, "black_frames": 0},
            "modules": {
                "metadata": {
                    "module_name": "Metadata",
                    "status": "completed",
                    "events": [],
                    "data": {
                        "video": {
                            "path": "sample.mp4",
                            "width": 160,
                            "height": 90,
                            "fps": 25.0,
                            "duration": 1.0,
                        }
                    },
                },
                "frame_issues": {
                    "module_name": "Frame Issues",
                    "status": "completed",
                    "events": [],
                    "data": {},
                    "errors": [],
                },
            },
        }

        sys.modules.pop("app", None)
        fake_streamlit = MagicMock()
        fake_pandas = MagicMock()
        fake_streamlit.session_state = {}
        with patch.dict(sys.modules, {"streamlit": fake_streamlit, "pandas": fake_pandas}):
            app = importlib.import_module("app")

        with (
            patch.object(app, "st") as streamlit,
            patch.object(app, "render_event_table"),
            patch.object(app, "render_event_review_list"),
            patch.object(app, "log_debug_info"),
        ):
            streamlit.session_state = {}
            streamlit.columns.side_effect = lambda spec: [MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]
            streamlit.tabs.return_value = [MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()]
            streamlit.slider.return_value = 0.7
            streamlit.selectbox.return_value = "全部异常"
            streamlit.expander.return_value.__enter__.return_value = MagicMock()

            app.render_report(report, Path("."))


class FailingAnalyzer(BaseAnalyzer):
    module_id = "broken"
    module_name = "Broken"

    def run(self, context: VideoContext) -> ModuleResult:
        raise RuntimeError("boom")


class PassingAnalyzer(BaseAnalyzer):
    module_id = "ok"
    module_name = "OK"

    def run(self, context: VideoContext) -> ModuleResult:
        return ModuleResult(module_id=self.module_id, module_name=self.module_name)


class FakeMetadata:
    width = 160
    height = 90
    fps = 25.0
    duration = 1.0
    codec = "mp4v"
    frame_count = 4
    audio_stream_exists = True

    def to_report(self, path: Path) -> dict:
        return {
            "path": str(path),
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration": self.duration,
            "codec": self.codec,
            "frame_count": self.frame_count,
            "audio_stream_exists": self.audio_stream_exists,
        }


def fake_frame_metrics() -> list[FrameMetric]:
    return [
        FrameMetric(0, 0.00, 40.0, 12.0, 0.05, None, None, None, None),
        FrameMetric(1, 0.04, 42.0, 13.0, 0.05, 4.0, 0.04, 4.0, 0.1),
        FrameMetric(2, 0.08, 44.0, 13.0, 0.05, 5.0, 0.04, 5.0, 0.1),
        FrameMetric(3, 0.12, 46.0, 13.0, 0.05, 4.5, 0.04, 4.5, 0.1),
    ]


def duplicate_events_for_pattern() -> list[dict]:
    return [
        {
            "type": "duplicate_frame",
            "start_frame": frame,
            "end_frame": frame,
            "reason": "该帧与上一帧差异极低。",
        }
        for frame in range(0, 275, 25)
    ]


if __name__ == "__main__":
    unittest.main()
