"""
Unit tests for MT5Executor._normalize_volume function
"""
import unittest
from unittest.mock import Mock
from core.execution.mt5_executor import MT5Executor


class TestNormalizeVolume(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.executor = MT5Executor()
    
    def test_normalize_volume_too_small(self):
        """Test that volume is increased to minimum when too small"""
        # Create mock symbol info with realistic MT5 values
        mock_symbol_info = Mock()
        mock_symbol_info.volume_min = 0.01
        mock_symbol_info.volume_max = 100.0
        mock_symbol_info.volume_step = 0.01
        mock_symbol_info.name = "EURUSD"
        
        # Input volume that's too small
        input_volume = 0.001
        expected = 0.01  # Should be adjusted to minimum
        
        result = self.executor._normalize_volume(input_volume, mock_symbol_info)
        self.assertEqual(result, expected)
    
    def test_normalize_volume_not_multiple_of_step(self):
        """Test that volume is adjusted to match step increment"""
        # Create mock symbol info with realistic MT5 values
        mock_symbol_info = Mock()
        mock_symbol_info.volume_min = 0.01
        mock_symbol_info.volume_max = 100.0
        mock_symbol_info.volume_step = 0.01
        mock_symbol_info.name = "EURUSD"
        
        # Input volume that's not a multiple of step
        input_volume = 0.023  # Not a multiple of 0.01
        expected = 0.02  # Should be adjusted down to nearest step multiple
        
        result = self.executor._normalize_volume(input_volume, mock_symbol_info)
        self.assertEqual(result, expected)
    
    def test_normalize_volume_too_large(self):
        """Test that volume is reduced to maximum when too large"""
        # Create mock symbol info with realistic MT5 values
        mock_symbol_info = Mock()
        mock_symbol_info.volume_min = 0.01
        mock_symbol_info.volume_max = 10.0
        mock_symbol_info.volume_step = 0.01
        mock_symbol_info.name = "EURUSD"
        
        # Input volume that's too large
        input_volume = 50.0
        expected = 10.0  # Should be adjusted to maximum
        
        result = self.executor._normalize_volume(input_volume, mock_symbol_info)
        self.assertEqual(result, expected)
    
    def test_normalize_volume_within_range(self):
        """Test that volume stays unchanged when within acceptable range"""
        # Create mock symbol info with realistic MT5 values
        mock_symbol_info = Mock()
        mock_symbol_info.volume_min = 0.01
        mock_symbol_info.volume_max = 100.0
        mock_symbol_info.volume_step = 0.01
        mock_symbol_info.name = "EURUSD"
        
        # Input volume that's already a proper multiple of step and within range
        input_volume = 0.15
        expected = 0.15  # Should remain unchanged
        
        result = self.executor._normalize_volume(input_volume, mock_symbol_info)
        self.assertEqual(result, expected)
    
    def test_normalize_volume_exact_step_multiple(self):
        """Test that volume is properly adjusted when exactly on step boundary"""
        # Create mock symbol info
        mock_symbol_info = Mock()
        mock_symbol_info.volume_min = 0.1
        mock_symbol_info.volume_max = 50.0
        mock_symbol_info.volume_step = 0.1
        mock_symbol_info.name = "GBPUSD"
        
        # Input volume that's exactly a step multiple
        input_volume = 0.25
        # Since step is 0.1, the function should adjust to 0.2 (the lower multiple)
        expected = 0.2
        
        result = self.executor._normalize_volume(input_volume, mock_symbol_info)
        self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()