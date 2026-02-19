"""
Unit tests for app/utils/sessionnet.py
"""
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from app.utils.sessionnet import calculate_sessionnet_params


class TestCalculateSessionnetParams:
    """Tests for calculate_sessionnet_params function."""

    def test_returns_dict_with_required_keys(self):
        """Test that function returns dict with all required keys."""
        params = calculate_sessionnet_params()
        
        required_keys = ["__cjahr", "__cmonat", "__canz", "smccont", "__cselect"]
        for key in required_keys:
            assert key in params

    def test_cjahr_is_current_year(self):
        """Test that __cjahr is set to current year."""
        params = calculate_sessionnet_params()
        current_year = datetime.now().year
        
        assert params["__cjahr"] == current_year

    def test_cmonat_is_six_months_ago(self):
        """Test that __cmonat is set to month from 6 months ago."""
        params = calculate_sessionnet_params()
        
        now = datetime.now()
        six_months_ago = now.replace(month=now.month - 6 if now.month > 6 else now.month + 6)
        expected_month = six_months_ago.month
        
        assert params["__cmonat"] == expected_month

    def test_canz_is_six(self):
        """Test that __canz is set to 6."""
        params = calculate_sessionnet_params()
        
        assert params["__canz"] == 6

    def test_smccont_is_twelve(self):
        """Test that smccont is set to 12."""
        params = calculate_sessionnet_params()
        
        assert params["smccont"] == 12

    def test_cselect_is_81920(self):
        """Test that __cselect is set to 81920."""
        params = calculate_sessionnet_params()
        
        assert params["__cselect"] == 81920

    @patch('app.utils.sessionnet.datetime')
    def test_year_boundary_january(self, mock_datetime):
        """Test month calculation when current month is January."""
        # Mock January 2024
        mock_now = MagicMock()
        mock_now.year = 2024
        mock_now.month = 1
        mock_now.__sub__ = lambda self, other: MagicMock(month=7)  # 6 months before Jan is July
        mock_datetime.now.return_value = mock_now
        
        params = calculate_sessionnet_params()
        
        # January - 6 months = July (month 7)
        assert params["__cmonat"] == 7
        assert params["__cjahr"] == 2024

    @patch('app.utils.sessionnet.datetime')
    def test_year_boundary_june(self, mock_datetime):
        """Test month calculation when current month is June."""
        mock_now = MagicMock()
        mock_now.year = 2024
        mock_now.month = 6
        mock_datetime.now.return_value = mock_now
        
        # Create mock for timedelta result
        six_months_ago = MagicMock()
        six_months_ago.month = 12  # December
        
        mock_datetime.now.return_value = mock_now
        
        # Patch the timedelta to return our mock
        with patch('app.utils.sessionnet.timedelta') as mock_timedelta:
            mock_timedelta.return_value = MagicMock()
            # We need to patch the subtraction result
            mock_now.__sub__ = MagicMock(return_value=six_months_ago)
            
            params = calculate_sessionnet_params()
            
            assert params["__cjahr"] == 2024

    @patch('app.utils.sessionnet.datetime')
    def test_year_boundary_december(self, mock_datetime):
        """Test month calculation when current month is December."""
        mock_now = MagicMock()
        mock_now.year = 2024
        mock_now.month = 12
        mock_datetime.now.return_value = mock_now
        
        # Create mock for timedelta result (6 months ago = June)
        six_months_ago = MagicMock()
        six_months_ago.month = 6
        
        with patch('app.utils.sessionnet.timedelta') as mock_timedelta:
            mock_result = MagicMock()
            mock_result.month = 6
            mock_now.__sub__ = MagicMock(return_value=mock_result)
            
            params = calculate_sessionnet_params()
            
            assert params["__cjahr"] == 2024