import unittest

from framesentry.metrics import adaptive_thresholds, median_abs_deviation, percentile


class MetricsTests(unittest.TestCase):
    def test_percentile_interpolates_values(self):
        self.assertEqual(percentile([1, 2, 3, 4], 0.5), 2.5)

    def test_median_abs_deviation(self):
        self.assertEqual(median_abs_deviation([1, 1, 2, 3, 100]), 1)

    def test_adaptive_thresholds_have_expected_keys(self):
        thresholds = adaptive_thresholds([1, 2, 3, 20, 40])
        self.assertGreater(thresholds["p95_diff"], thresholds["median_diff"])
        self.assertGreaterEqual(thresholds["high_diff"], 18)
        self.assertGreaterEqual(thresholds["very_low_diff"], 1)


if __name__ == "__main__":
    unittest.main()
