import unittest

from framesentry.utils.timecode import frame_to_timecode, seconds_to_timecode


class TimecodeTests(unittest.TestCase):
    def test_frame_to_timecode_integer_fps(self):
        self.assertEqual(frame_to_timecode(318, 25), "00:00:12:18")

    def test_frame_to_timecode_rolls_frame_number(self):
        self.assertEqual(frame_to_timecode(30, 30), "00:00:01:00")

    def test_frame_to_timecode_unknown_fps(self):
        self.assertEqual(frame_to_timecode(10, 0), "00:00:00:00")

    def test_seconds_to_timecode(self):
        self.assertEqual(seconds_to_timecode(0), "00:00:00")
        self.assertEqual(seconds_to_timecode(65.9), "00:01:05")
        self.assertEqual(seconds_to_timecode(3661), "01:01:01")


if __name__ == "__main__":
    unittest.main()
