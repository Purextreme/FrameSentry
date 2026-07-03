from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from framesentry.cache import ReportCacheManager, video_fingerprint
from framesentry.scanner import RUNTIME_CACHE_KEY, analysis_options, scan_video


class CacheTests(unittest.TestCase):
    def test_report_cache_matches_same_video_even_when_options_differ(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"video")
            report_path = root / "output" / "reports" / "clip_001" / "report.json"
            write_report(report_path, video, sample_scale=480)

            hit = ReportCacheManager(root / "output").find(video)

        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.report_path, report_path)
        self.assertEqual(
            hit.report["modules"]["frame_issues"]["data"]["analysis_options"],
            analysis_options(sample_scale=480, max_outlier_frames=2, save_screenshots=True),
        )

    def test_report_cache_misses_when_video_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"video")
            report_path = root / "output" / "reports" / "clip_001" / "report.json"
            write_report(report_path, video)
            video.write_bytes(b"changed video")

            hit = ReportCacheManager(root / "output").find(video)

        self.assertIsNone(hit)

    def test_report_cache_skips_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"video")
            report_path = root / "output" / "reports" / "clip_001" / "report.json"
            report_path.parent.mkdir(parents=True)
            report_path.write_text("{", encoding="utf-8")

            hit = ReportCacheManager(root / "output").find(video)

        self.assertIsNone(hit)

    def test_cached_report_can_have_missing_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"video")
            report_path = root / "output" / "reports" / "clip_001" / "report.json"
            write_report(report_path, video, include_frame_issues=False)

            hit = ReportCacheManager(root / "output").find(video)

        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertNotIn("frame_issues", hit.report["modules"])

    def test_scan_video_returns_cached_report_without_running_analyzers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"video")
            cached_report_path = root / "output" / "reports" / "clip_001" / "report.json"
            write_report(cached_report_path, video, include_frame_issues=False)

            with patch("framesentry.scanner.AnalysisRunner") as runner_class:
                report = scan_video(
                    video,
                    root / "new_report",
                    use_cache=True,
                    cache_root=root / "output",
                )

        runner_class.assert_not_called()
        self.assertTrue(report[RUNTIME_CACHE_KEY]["cache_hit"])
        self.assertEqual(report[RUNTIME_CACHE_KEY]["report_path"], str(cached_report_path))
        self.assertNotIn("frame_issues", report["modules"])

    def test_scan_video_can_bypass_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"video")
            cached_report_path = root / "output" / "reports" / "clip_001" / "report.json"
            write_report(cached_report_path, video)

            with (
                patch("framesentry.scanner.AnalysisRunner") as runner_class,
                patch("framesentry.scanner.ReportBuilder") as builder_class,
            ):
                runner_class.return_value.run.return_value = {}
                builder_class.return_value.build.return_value = {"video": {}, "summary": {}, "modules": {}}
                report = scan_video(
                    video,
                    root / "new_report",
                    use_cache=False,
                    cache_root=root / "output",
                )

        runner_class.assert_called_once()
        self.assertFalse(report[RUNTIME_CACHE_KEY]["cache_hit"])


def write_report(
    report_path: Path,
    video: Path,
    *,
    sample_scale: int = 480,
    include_frame_issues: bool = True,
) -> None:
    modules = {
        "metadata": {
            "data": {
                "source_file": video_fingerprint(video),
            },
            "events": [],
        },
    }
    if include_frame_issues:
        modules["frame_issues"] = {
            "data": {
                "analysis_options": analysis_options(
                    sample_scale=sample_scale,
                    max_outlier_frames=2,
                    save_screenshots=True,
                ),
            },
            "events": [],
        }
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({"modules": modules}), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
