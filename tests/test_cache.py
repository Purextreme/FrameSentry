from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from framesentry.cache import analysis_options, find_cached_report, video_fingerprint


class CacheTests(unittest.TestCase):
    def test_find_cached_report_requires_matching_file_and_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"video")
            report_dir = root / "output" / "reports" / "clip_001"
            report_dir.mkdir(parents=True)
            report_path = report_dir / "report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "modules": {
                            "metadata": {
                                "data": {
                                    "source_file": video_fingerprint(video),
                                },
                                "events": [],
                            },
                            "frame_issues": {
                                "data": {
                                    "analysis_options": analysis_options(
                                        sample_scale=480,
                                        max_outlier_frames=2,
                                        save_screenshots=True,
                                    ),
                                },
                                "events": [],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            hit = find_cached_report(
                video,
                output_root=root / "output",
                sample_scale=480,
                max_outlier_frames=2,
                save_screenshots=True,
            )
            miss = find_cached_report(
                video,
                output_root=root / "output",
                sample_scale=320,
                max_outlier_frames=2,
                save_screenshots=True,
            )

        self.assertEqual(hit, report_path)
        self.assertIsNone(miss)

    def test_screenshot_cache_requires_screenshot_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"video")
            report_dir = root / "output" / "reports" / "clip_001"
            report_dir.mkdir(parents=True)
            report_path = report_dir / "report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "modules": {
                            "metadata": {
                                "data": {
                                    "source_file": video_fingerprint(video),
                                },
                                "events": [],
                            },
                            "frame_issues": {
                                "data": {
                                    "analysis_options": analysis_options(
                                        sample_scale=480,
                                        max_outlier_frames=2,
                                        save_screenshots=True,
                                    ),
                                },
                                "events": [
                                    {
                                        "type": "duplicate_frame",
                                        "start_frame": 10,
                                        "end_frame": 10,
                                    }
                                ],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            miss = find_cached_report(
                video,
                output_root=root / "output",
                sample_scale=480,
                max_outlier_frames=2,
                save_screenshots=True,
            )
            hit_without_screenshot_requirement = find_cached_report(
                video,
                output_root=root / "output",
                sample_scale=480,
                max_outlier_frames=2,
                save_screenshots=False,
            )

        self.assertIsNone(miss)
        self.assertEqual(hit_without_screenshot_requirement, report_path)


if __name__ == "__main__":
    unittest.main()
