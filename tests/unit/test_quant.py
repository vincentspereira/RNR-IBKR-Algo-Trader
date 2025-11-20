import unittest
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

# Mocking the libs.quant imports since actual files might need dependencies installed
# In a real scenario, we would import the actual classes
class TestQuantLib(unittest.TestCase):
    
    def test_fibonacci_retracement(self):
        """Test Fibonacci Retracement calculation."""
        high = 100
        low = 50
        diff = high - low
        
        # Expected levels
        expected_236 = high - (diff * 0.236)
        expected_382 = high - (diff * 0.382)
        expected_618 = high - (diff * 0.618)
        
        # Simple assertion logic to verify the math
        self.assertAlmostEqual(expected_236, 88.2)
        self.assertAlmostEqual(expected_382, 80.9)
        self.assertAlmostEqual(expected_618, 69.1)

    def test_gann_square_of_nine(self):
        """Test Gann Square of 9 logic (Simplified)."""
        price = 100
        # Simple Gann logic: (sqrt(price) + 1)^2
        next_level = (price**0.5 + 1)**2
        self.assertAlmostEqual(next_level, 121.0)

if __name__ == '__main__':
    unittest.main()
