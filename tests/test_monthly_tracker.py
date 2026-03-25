"""Tests for monthly usage tracker"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.monthly_tracker import (
    _get_usage_file_path,
    _load_usage,
    _save_usage,
    _get_current_month,
    check_month_rollover,
    add_minutes_used,
    get_usage_info,
    fetch_github_actions_minutes,
    update_github_minutes,
)


class TestGetUsageFilePath:
    """Tests for _get_usage_file_path function"""

    def test_returns_correct_path(self, mock_settings, temp_dir):
        """Test that correct path is constructed"""
        mock_settings.state_file_dir = temp_dir

        with patch("src.monthly_tracker.get_settings", return_value=mock_settings):
            path = _get_usage_file_path()

            assert str(path).endswith("monthly_usage.json")
            assert temp_dir in str(path)


class TestLoadSaveUsage:
    """Tests for _load_usage and _save_usage functions"""

    def test_load_returns_defaults_when_no_file(self, mock_settings, temp_dir):
        """Test that default values are returned when file doesn't exist"""
        mock_settings.state_file_dir = temp_dir

        with patch("src.monthly_tracker.get_settings", return_value=mock_settings):
            usage = _load_usage()

            assert usage["year"] == 0
            assert usage["month"] == 0
            assert usage["minutes_used"] == 0

    def test_load_reads_existing_file(self, mock_settings, temp_dir):
        """Test that existing file is loaded"""
        mock_settings.state_file_dir = temp_dir

        # Create usage file
        usage_file = Path(temp_dir) / "monthly_usage.json"
        usage_file.write_text(json.dumps({
            "year": 2024,
            "month": 3,
            "minutes_used": 100.5,
            "github_minutes_used": 50.0
        }))

        with patch("src.monthly_tracker.get_settings", return_value=mock_settings):
            usage = _load_usage()

            assert usage["year"] == 2024
            assert usage["month"] == 3
            assert usage["minutes_used"] == 100.5

    def test_load_handles_corrupt_file(self, mock_settings, temp_dir):
        """Test that corrupt JSON is handled gracefully"""
        mock_settings.state_file_dir = temp_dir

        usage_file = Path(temp_dir) / "monthly_usage.json"
        usage_file.write_text("not valid json")

        with patch("src.monthly_tracker.get_settings", return_value=mock_settings):
            usage = _load_usage()

            assert usage["year"] == 0

    def test_save_creates_file(self, mock_settings, temp_dir):
        """Test that save creates the usage file"""
        mock_settings.state_file_dir = temp_dir

        usage = {"year": 2024, "month": 3, "minutes_used": 100, "github_minutes_used": 0}

        with patch("src.monthly_tracker.get_settings", return_value=mock_settings):
            _save_usage(usage)

            usage_file = Path(temp_dir) / "monthly_usage.json"
            assert usage_file.exists()

            loaded = json.loads(usage_file.read_text())
            assert loaded["year"] == 2024
            assert loaded["minutes_used"] == 100

    def test_save_creates_directory(self, mock_settings, temp_dir):
        """Test that save creates parent directory if needed"""
        new_dir = os.path.join(temp_dir, "new_state")
        mock_settings.state_file_dir = new_dir

        usage = {"year": 2024, "month": 3, "minutes_used": 100, "github_minutes_used": 0}

        with patch("src.monthly_tracker.get_settings", return_value=mock_settings):
            _save_usage(usage)

            assert os.path.exists(new_dir)


class TestGetCurrentMonth:
    """Tests for _get_current_month function"""

    def test_returns_year_and_month(self):
        """Test that year and month are returned"""
        year, month = _get_current_month()

        assert isinstance(year, int)
        assert isinstance(month, int)
        assert 1 <= month <= 12
        assert year >= 2024


class TestCheckMonthRollover:
    """Tests for check_month_rollover function"""

    def test_resets_on_new_month(self, mock_settings, temp_dir):
        """Test that usage is reset when month changes"""
        mock_settings.state_file_dir = temp_dir

        # Create usage file with old month
        usage_file = Path(temp_dir) / "monthly_usage.json"
        usage_file.write_text(json.dumps({
            "year": 2020,
            "month": 1,
            "minutes_used": 100,
            "github_minutes_used": 50
        }))

        with patch("src.monthly_tracker.get_settings", return_value=mock_settings):
            result = check_month_rollover()

            assert result is True  # Was reset

            usage = _load_usage()
            current_year, current_month = _get_current_month()
            assert usage["year"] == current_year
            assert usage["month"] == current_month
            assert usage["minutes_used"] == 0

    def test_no_reset_same_month(self, mock_settings, temp_dir):
        """Test that usage is not reset when same month"""
        mock_settings.state_file_dir = temp_dir

        current_year, current_month = _get_current_month()

        # Create usage file with current month
        usage_file = Path(temp_dir) / "monthly_usage.json"
        usage_file.write_text(json.dumps({
            "year": current_year,
            "month": current_month,
            "minutes_used": 100,
            "github_minutes_used": 50
        }))

        with patch("src.monthly_tracker.get_settings", return_value=mock_settings):
            result = check_month_rollover()

            assert result is False  # Was not reset

            usage = _load_usage()
            assert usage["minutes_used"] == 100


class TestAddMinutesUsed:
    """Tests for add_minutes_used function"""

    def test_increments_counter(self, mock_settings, temp_dir):
        """Test that minutes are added to counter"""
        mock_settings.state_file_dir = temp_dir

        current_year, current_month = _get_current_month()

        with patch("src.monthly_tracker.get_settings", return_value=mock_settings):
            add_minutes_used(30.5)

            usage = _load_usage()
            assert usage["minutes_used"] == 30.5

            add_minutes_used(10)

            usage = _load_usage()
            assert usage["minutes_used"] == 40.5


class TestGetUsageInfo:
    """Tests for get_usage_info function"""

    def test_returns_usage_dict(self, mock_settings, temp_dir):
        """Test that usage info dict is returned"""
        mock_settings.state_file_dir = temp_dir
        mock_settings.monthly_minutes_limit = 2000

        with patch("src.monthly_tracker.get_settings", return_value=mock_settings):
            info = get_usage_info()

            assert "year" in info
            assert "month" in info
            assert "minutes_used" in info
            assert "limit" in info
            assert "remaining" in info


class TestFetchGithubActionsMinutes:
    """Tests for fetch_github_actions_minutes function"""

    def test_returns_zero_on_gh_error(self, mock_settings):
        """Test that 0 is returned when gh CLI fails"""
        mock_settings.github_repo = "owner/repo"

        with patch("src.monthly_tracker.get_settings", return_value=mock_settings):
            with patch("subprocess.run", side_effect=Exception("gh not found")):
                minutes = fetch_github_actions_minutes()

                assert minutes == 0

    def test_returns_zero_when_no_repo(self, mock_settings):
        """Test that 0 is returned when repo can't be determined"""
        mock_settings.github_repo = None

        with patch("src.monthly_tracker.get_settings", return_value=mock_settings):
            with patch("subprocess.run", side_effect=Exception("No repo")):
                minutes = fetch_github_actions_minutes()

                assert minutes == 0


class TestUpdateGithubMinutes:
    """Tests for update_github_minutes function"""

    def test_updates_github_minutes(self, mock_settings, temp_dir):
        """Test that GitHub minutes are updated in usage file"""
        mock_settings.state_file_dir = temp_dir

        with patch("src.monthly_tracker.get_settings", return_value=mock_settings):
            with patch("src.monthly_tracker.fetch_github_actions_minutes", return_value=123.45):
                update_github_minutes()

                usage = _load_usage()
                assert usage["github_minutes_used"] == 123.45
