from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from framesentry.utils.screenshots import _save_frame


class ScreenshotTests(unittest.TestCase):
    def test_save_frame_supports_unicode_path(self) -> None:
        try:
            import cv2
            import numpy as np
        except ModuleNotFoundError:
            self.skipTest("OpenCV or numpy is not installed")

        class FakeCapture:
            def set(self, prop_id, value) -> None:
                self.prop_id = prop_id
                self.value = value

            def read(self):
                frame = np.full((16, 16, 3), 128, dtype=np.uint8)
                return True, frame

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "截图目录"
            output_dir.mkdir()
            output_path = output_dir / "测试帧.jpg"

            saved = _save_frame(FakeCapture(), 3, output_path)

            self.assertTrue(saved)
            self.assertTrue(output_path.exists())
            self.assertGreater(output_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
