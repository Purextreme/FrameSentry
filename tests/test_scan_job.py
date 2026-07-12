from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from framesentry.analysis import AnalyzerRegistry, BaseAnalyzer, ModuleResult, VideoContext
from framesentry.scan_job import ScanJob


class ScanJobTests(unittest.TestCase):
    def test_metadata_result_is_visible_before_later_module_finishes(self) -> None:
        started = Event()
        release = Event()
        registry = AnalyzerRegistry()
        registry.register(MetadataAnalyzer())
        registry.register(BlockingAnalyzer(started, release))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = VideoContext(video_path=root / "video.mp4", output_dir=root, video_id="video")
            with patch("framesentry.scan_job.default_registry", return_value=registry):
                job = ScanJob(context, root / "report.json")
                job.start()
                self.assertTrue(started.wait(timeout=2))

                snapshot = job.snapshot()
                self.assertEqual(snapshot["modules"]["metadata"]["status"], "completed")
                self.assertEqual(snapshot["modules"]["slow"]["status"], "running")
                self.assertEqual(snapshot["modules"]["metadata"]["data"]["video"]["fps"], 25.0)

                snapshot["modules"]["metadata"]["status"] = "changed"
                self.assertEqual(job.snapshot()["modules"]["metadata"]["status"], "completed")

                release.set()
                final = wait_for_terminal(job)
                self.assertEqual(final["status"], "completed")
                self.assertTrue((root / "report.json").exists())


class MetadataAnalyzer(BaseAnalyzer):
    module_id = "metadata"
    module_name = "Metadata"

    def run(self, context: VideoContext) -> ModuleResult:
        return ModuleResult(
            module_id=self.module_id,
            module_name=self.module_name,
            data={"video": {"path": str(context.video_path), "fps": 25.0}},
        )


class BlockingAnalyzer(BaseAnalyzer):
    module_id = "slow"
    module_name = "Slow"

    def __init__(self, started: Event, release: Event) -> None:
        self.started = started
        self.release = release

    def run(self, context: VideoContext) -> ModuleResult:
        self.started.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("test did not release analyzer")
        return ModuleResult(module_id=self.module_id, module_name=self.module_name)


def wait_for_terminal(job: ScanJob) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        snapshot = job.snapshot()
        if snapshot["status"] in {"completed", "failed"}:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("scan job did not finish")


if __name__ == "__main__":
    unittest.main()
