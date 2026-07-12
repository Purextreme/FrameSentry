from __future__ import annotations

import unittest
from unittest.mock import patch

import app


class FileDialogTests(unittest.TestCase):
    @staticmethod
    def _complete_dialog(command, **kwargs):
        app.Path(command[-1]).write_text("D:\\视频\\示例片段.mp4", encoding="utf-8")
        return app.subprocess.CompletedProcess(command, 0, "", "")

    def test_choose_file_returns_utf8_result_file(self) -> None:
        with patch.object(app.subprocess, "run", side_effect=self._complete_dialog) as run:
            path = app._choose_file(title="选择视频", filetypes=[("视频文件", "*.mp4")])

        self.assertEqual(path, "D:\\视频\\示例片段.mp4")
        self.assertEqual(run.call_args.args[0][0], app.sys.executable)

    def test_choose_file_returns_empty_when_dialog_process_fails(self) -> None:
        completed = app.subprocess.CompletedProcess([], 1, "", "dialog failed")

        with patch.object(app.subprocess, "run", return_value=completed):
            path = app._choose_file(title="选择视频", filetypes=[("视频文件", "*.mp4")])

        self.assertEqual(path, "")

    def test_choose_file_returns_empty_when_child_has_no_result_file(self) -> None:
        completed = app.subprocess.CompletedProcess([], 0, None, None)

        with patch.object(app.subprocess, "run", return_value=completed):
            path = app._choose_file(title="选择视频", filetypes=[("视频文件", "*.mp4")])

        self.assertEqual(path, "")


if __name__ == "__main__":
    unittest.main()
