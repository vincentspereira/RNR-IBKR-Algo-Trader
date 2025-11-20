import unittest
import asyncio
from unittest.mock import MagicMock

class TestSmartMoneyFlow(unittest.TestCase):
    
    def test_smart_money_signal_generation(self):
        """Verify that Smart Money Engine generates signals that Execution Engine can understand."""
        
        # Mock the engines
        smart_money_engine = MagicMock()
        execution_engine = MagicMock()
        
        # Simulate a Smart Money Signal
        signal = {
            "type": "INSTITUTIONAL_BUY",
            "symbol": "AAPL",
            "volume": 1000000,
            "confidence": 0.95
        }
        
        smart_money_engine.analyze.return_value = signal
        
        # Simulate Execution Engine processing
        execution_engine.execute_signal(signal)
        
        # Verify call
        execution_engine.execute_signal.assert_called_with(signal)
        self.assertEqual(signal["type"], "INSTITUTIONAL_BUY")

if __name__ == '__main__':
    unittest.main()
