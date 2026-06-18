import unittest

from framesentry.detectors.duplicate_frame import detect_duplicate_frames
from framesentry.detectors.transient_outlier import detect_transient_outliers
from framesentry.frame_reader import FrameMetric
from framesentry.metrics import adaptive_thresholds


def metric(index, diff, *, hist_diff=None, coverage=None):
    return FrameMetric(
        frame_index=index,
        timestamp=index / 25,
        mean_luma=50,
        std_luma=20,
        edge_density=0.1,
        pixel_diff_to_prev=diff,
        hist_diff_to_prev=hist_diff,
        block_mean_diff_to_prev=diff,
        block_change_ratio_to_prev=coverage,
    )


def low_detail_metric(index, diff):
    return FrameMetric(
        frame_index=index,
        timestamp=index / 25,
        mean_luma=0,
        std_luma=0,
        edge_density=0,
        pixel_diff_to_prev=diff,
        hist_diff_to_prev=None,
        block_mean_diff_to_prev=diff,
        block_change_ratio_to_prev=0,
    )


class DetectorTests(unittest.TestCase):
    def test_detect_duplicate_frame_with_motion_context(self):
        diffs = [None, 12, 14, 13, 0.2, 16, 15, 14]
        metrics = [metric(index, diff) for index, diff in enumerate(diffs)]
        thresholds = adaptive_thresholds([diff for diff in diffs if diff is not None])

        events = detect_duplicate_frames(metrics, 25, thresholds, window=3)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "duplicate_frame")
        self.assertEqual(events[0]["start_frame"], 4)

    def test_duplicate_detector_skips_low_detail_frames(self):
        metrics = [
            metric(0, None),
            metric(1, 12),
            metric(2, 13),
            low_detail_metric(3, 0.1),
            low_detail_metric(4, 0.1),
            metric(5, 15),
            metric(6, 14),
        ]
        thresholds = adaptive_thresholds([12, 13, 0.1, 0.1, 15, 14])

        events = detect_duplicate_frames(metrics, 25, thresholds, window=3)

        self.assertEqual(events, [])

    def test_duplicate_detector_skips_large_color_change(self):
        metrics = [
            metric(0, None),
            metric(1, 12),
            metric(2, 13),
            metric(3, 0.1, hist_diff=0.9),
            metric(4, 15),
            metric(5, 14),
        ]
        thresholds = adaptive_thresholds([12, 13, 0.1, 15, 14])

        events = detect_duplicate_frames(metrics, 25, thresholds, window=3)

        self.assertEqual(events, [])

    def test_detect_transient_outlier_single_frame(self):
        diffs = [None, 2, 2, 2, 40, 42, 2, 2, 2]
        metrics = [
            metric(index, diff, hist_diff=0.8 if diff and diff >= 40 else 0.05, coverage=1.0 if diff and diff >= 40 else 0.1)
            for index, diff in enumerate(diffs)
        ]
        thresholds = adaptive_thresholds([2, 2, 2, 2, 2, 40, 42])

        events = detect_transient_outliers(metrics, 25, thresholds, max_outlier_frames=1, window=3)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "transient_outlier")
        self.assertEqual(events[0]["start_frame"], 4)

    def test_detect_transient_outlier_two_frame_segment(self):
        diffs = [None, 2, 2, 2, 40, 1, 42, 2, 2]
        metrics = [
            metric(index, diff, hist_diff=0.8 if diff and diff >= 40 else 0.05, coverage=1.0 if diff and diff >= 40 else 0.1)
            for index, diff in enumerate(diffs)
        ]
        thresholds = adaptive_thresholds([2, 2, 2, 2, 2, 1, 40, 42])

        events = detect_transient_outliers(metrics, 25, thresholds, max_outlier_frames=2, window=3)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["start_frame"], 4)
        self.assertEqual(events[0]["end_frame"], 5)
        self.assertEqual(events[0]["duration_frames"], 2)

    def test_normal_cut_is_not_transient_outlier(self):
        diffs = [None, 2, 2, 2, 40, 2, 2, 2]
        metrics = [
            metric(index, diff, hist_diff=0.8 if diff and diff >= 40 else 0.05, coverage=1.0 if diff and diff >= 40 else 0.1)
            for index, diff in enumerate(diffs)
        ]
        thresholds = adaptive_thresholds([2, 2, 2, 2, 2, 40])

        events = detect_transient_outliers(metrics, 25, thresholds, max_outlier_frames=1, window=3)

        self.assertEqual(events, [])

    def test_local_fast_motion_is_review_not_transient_outlier(self):
        diffs = [None, 2, 2, 2, 40, 42, 2, 2, 2]
        metrics = [
            metric(index, diff, hist_diff=0.12 if diff and diff >= 40 else 0.05, coverage=0.25 if diff and diff >= 40 else 0.1)
            for index, diff in enumerate(diffs)
        ]
        thresholds = adaptive_thresholds([2, 2, 2, 2, 2, 40, 42])

        events = detect_transient_outliers(metrics, 25, thresholds, max_outlier_frames=1, window=3)

        self.assertFalse(any(event["type"] == "transient_outlier" for event in events))


if __name__ == "__main__":
    unittest.main()
