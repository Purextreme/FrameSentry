from __future__ import annotations

import unittest

from framesentry.analyzers import default_registry


class DefaultRegistryTests(unittest.TestCase):
    def test_llm_subtitle_detection_is_enabled(self) -> None:
        module_ids = [analyzer.module_id for analyzer in default_registry().analyzers()]

        self.assertEqual(
            module_ids,
            ["metadata", "frame_issues", "color_analysis", "motion_analysis", "llm_subtitle_detection"],
        )


if __name__ == "__main__":
    unittest.main()
