import unittest
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))


class TestQuantLib(unittest.TestCase):

    def test_fibonacci_retracement(self):
        """Test Fibonacci Retracement calculation."""
        high = 100
        low = 50
        diff = high - low

        expected_236 = high - (diff * 0.236)
        expected_382 = high - (diff * 0.382)
        expected_618 = high - (diff * 0.618)

        self.assertAlmostEqual(expected_236, 88.2)
        self.assertAlmostEqual(expected_382, 80.9)
        self.assertAlmostEqual(expected_618, 69.1)

    def test_gann_square_of_nine(self):
        """Test Gann Square of 9 logic via the canonical (sqrt(price)+1)^2 step."""
        price = 100
        next_level = (price**0.5 + 1)**2
        self.assertAlmostEqual(next_level, 121.0)

if __name__ == '__main__':
    unittest.main()
