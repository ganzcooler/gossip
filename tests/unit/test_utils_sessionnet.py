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

    def test_cjahr_is_six_months_ago_year(self):
        """Test that __cjahr is set to year from 6 months ago."""
        params = calculate_sessionnet_params()
        now = datetime.now()
        six_months_ago = now.replace(year=now.year - 1) if now.month <= 6 else now
        expected_year = six_months_ago.year - (1 if now.month <= 6 else 0)
        
        # __cjahr is the year from 6 months ago
        actual_six_months_ago = now - __import__('datetime').timedelta(days=180)
        assert params["__cjahr"] == actual_six_months_ago.year

    def test_cmonat_is_six_months_ago(self):
        """Test that __cmonat is set to month from 6 months ago."""
        params = calculate_sessionnet_params()
        
        now = datetime.now()
        six_months_ago = now.replace(month=now.month - 6 if now.month > 6 else now.month + 6)
        expected_month = six_months_ago.month
        
        assert params["__cmonat"] == expected_month

    def test_canz_is_twelve(self):
        """Test that __canz is set to 12."""
        params = calculate_sessionnet_params()
        
        assert params["__canz"] == 12

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
        from datetime import timedelta
        
        # Create a real datetime for January 2024
        mock_now = datetime(2024, 1, 15)
        mock_datetime.now.return_value = mock_now
        
        # Mock timedelta to return a real datetime 6 months ago
        six_months_ago = datetime(2023, 7, 15)
        mock_datetime.timedelta = __import__('datetime').timedelta
        
        params = calculate_sessionnet_params()
        
        # January - 6 months = July (month 7), year becomes 2023
        assert params["__cmonat"] == 7
        assert params["__cjahr"] == 2023

    @patch('app.utils.sessionnet.datetime')
    def test_year_boundary_june(self, mock_datetime):
        """Test month calculation when current month is June."""
        # Create a real datetime for June 2024
        mock_now = datetime(2024, 6, 15)
        mock_datetime.now.return_value = mock_now
        mock_datetime.timedelta = __import__('datetime').timedelta
        
        params = calculate_sessionnet_params()
        
        # June - 6 months = December (month 12), year becomes 2023
        assert params["__cmonat"] == 12
        assert params["__cjahr"] == 2023

    @patch('app.utils.sessionnet.datetime')
    def test_year_boundary_december(self, mock_datetime):
        """Test month calculation when current month is December."""
        # Create a real datetime for December 2024
        mock_now = datetime(2024, 12, 15)
        mock_datetime.now.return_value = mock_now
        mock_datetime.timedelta = __import__('datetime').timedelta
        
        params = calculate_sessionnet_params()
        
        # December - 6 months = June (month 6), year stays 2024
        assert params["__cmonat"] == 6
        assert params["__cjahr"] == 2024