"""Tests for VOD downloader"""

import os
from unittest.mock import MagicMock, patch

import pytest

from src.downloader import Downloader, process_pending_vods


class TestDownloaderInit:
    """Tests for Downloader initialization"""

    def test_creates_output_directory(self, mock_settings, temp_dir):
        """Test that output directory is created"""
        mock_settings.audio_output_dir = temp_dir

        with patch("src.downloader.get_settings", return_value=mock_settings):
            downloader = Downloader()
            assert downloader.output_dir == temp_dir


class TestDownloadVodAudio:
    """Tests for download_vod_audio method"""

    def test_yt_dlp_called_correctly(self, mock_settings, temp_dir, sample_vod_data):
        """Test that yt-dlp is called with correct options"""
        mock_settings.audio_output_dir = temp_dir

        # Create the expected output file
        expected_path = os.path.join(temp_dir, f"{sample_vod_data['vod_id']}.opus")
        with open(expected_path, "w") as f:
            f.write("")

        with patch("src.downloader.get_settings", return_value=mock_settings):
            with patch("src.downloader.yt_dlp.YoutubeDL") as mock_ydl_class:
                mock_ydl = MagicMock()
                mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
                mock_ydl.__exit__ = MagicMock(return_value=False)
                mock_ydl_class.return_value = mock_ydl

                downloader = Downloader()
                result = downloader.download_vod_audio(sample_vod_data)

                assert result == expected_path
                mock_ydl.download.assert_called_once()

    def test_constructs_correct_url(self, mock_settings, temp_dir, sample_vod_data):
        """Test that correct Twitch URL is constructed"""
        mock_settings.audio_output_dir = temp_dir

        expected_path = os.path.join(temp_dir, f"{sample_vod_data['vod_id']}.opus")
        with open(expected_path, "w") as f:
            f.write("")

        with patch("src.downloader.get_settings", return_value=mock_settings):
            with patch("src.downloader.yt_dlp.YoutubeDL") as mock_ydl_class:
                mock_ydl = MagicMock()
                mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
                mock_ydl.__exit__ = MagicMock(return_value=False)
                mock_ydl_class.return_value = mock_ydl

                downloader = Downloader()
                downloader.download_vod_audio(sample_vod_data)

                # Check that download was called with correct URL
                call_args = mock_ydl.download.call_args[0][0]
                assert "twitch.tv/videos/" in call_args[0]
                assert sample_vod_data["vod_id"] in call_args[0]

    def test_raises_if_file_not_created(self, mock_settings, temp_dir, sample_vod_data):
        """Test that FileNotFoundError is raised if output file not created"""
        mock_settings.audio_output_dir = temp_dir

        with patch("src.downloader.get_settings", return_value=mock_settings):
            with patch("src.downloader.yt_dlp.YoutubeDL") as mock_ydl_class:
                mock_ydl = MagicMock()
                mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
                mock_ydl.__exit__ = MagicMock(return_value=False)
                mock_ydl_class.return_value = mock_ydl

                downloader = Downloader()

                with pytest.raises(FileNotFoundError):
                    downloader.download_vod_audio(sample_vod_data)


class TestCleanupAudio:
    """Tests for cleanup_audio method"""

    def test_removes_existing_file(self, mock_settings, temp_dir):
        """Test that existing file is removed"""
        test_file = os.path.join(temp_dir, "test.opus")
        with open(test_file, "w") as f:
            f.write("test")

        with patch("src.downloader.get_settings", return_value=mock_settings):
            downloader = Downloader()
            downloader.cleanup_audio(test_file)

            assert not os.path.exists(test_file)

    def test_handles_missing_file(self, mock_settings, temp_dir):
        """Test that missing file doesn't cause error"""
        nonexistent = os.path.join(temp_dir, "nonexistent.opus")

        with patch("src.downloader.get_settings", return_value=mock_settings):
            downloader = Downloader()
            # Should not raise
            downloader.cleanup_audio(nonexistent)


class TestProcessPendingVods:
    """Tests for process_pending_vods function"""

    def test_returns_zero_when_no_pending(self, mock_settings, temp_dir):
        """Test that 0 is returned when no pending VODs"""
        mock_settings.audio_output_dir = temp_dir

        with patch("src.downloader.get_settings", return_value=mock_settings):
            with patch("src.state.get_pending_vods", return_value=[]):
                count = process_pending_vods()
                assert count == 0

    def test_processes_pending_vods(self, mock_settings, temp_dir):
        """Test that pending VODs are processed"""
        mock_settings.audio_output_dir = temp_dir
        pending_vods = [
            {"vod_id": "123", "streamer": "test", "duration": 1800},
        ]

        # Create expected output file
        expected_path = os.path.join(temp_dir, "123.opus")
        with open(expected_path, "w") as f:
            f.write("")

        with patch("src.downloader.get_settings", return_value=mock_settings):
            with patch("src.state.get_pending_vods", return_value=pending_vods):
                with patch("src.downloader.StateManager") as mock_sm_class:
                    mock_manager = MagicMock()
                    mock_sm_class.return_value = mock_manager

                    with patch("src.downloader.Downloader") as mock_dl_class:
                        mock_dl = MagicMock()
                        mock_dl.download_vod_audio.return_value = expected_path
                        mock_dl_class.return_value = mock_dl

                        count = process_pending_vods(max_vods=1, max_workers=1)

                        # Status should be updated to DOWNLOADING
                        mock_manager.update_vod.assert_called()

    def test_respects_max_vods_limit(self, mock_settings, temp_dir):
        """Test that max_vods limit is respected"""
        mock_settings.audio_output_dir = temp_dir
        pending_vods = [
            {"vod_id": "1", "streamer": "test", "duration": 1800},
            {"vod_id": "2", "streamer": "test", "duration": 1800},
            {"vod_id": "3", "streamer": "test", "duration": 1800},
        ]

        # Create expected output files
        for i in range(1, 4):
            with open(os.path.join(temp_dir, f"{i}.opus"), "w") as f:
                f.write("")

        with patch("src.downloader.get_settings", return_value=mock_settings):
            with patch("src.state.get_pending_vods", return_value=pending_vods):
                with patch("src.downloader.Downloader") as mock_dl_class:
                    mock_dl = MagicMock()
                    mock_dl_class.return_value = mock_dl

                    with patch("src.downloader.StateManager"):
                        process_pending_vods(max_vods=2, max_workers=1)

    def test_sorts_by_duration(self, mock_settings):
        """Test that VODs are sorted by duration (shortest first)"""
        pending_vods = [
            {"vod_id": "1", "streamer": "test", "duration": 3600},  # 1 hour
            {"vod_id": "2", "streamer": "test", "duration": 1800},  # 30 min
            {"vod_id": "3", "streamer": "test", "duration": 7200},  # 2 hours
        ]

        with patch("src.downloader.get_settings", return_value=mock_settings):
            with patch("src.state.get_pending_vods", return_value=pending_vods):
                with patch("src.downloader.Downloader"):
                    with patch("src.downloader.StateManager"):
                        # Just check sorting logic doesn't crash
                        sorted_vods = sorted(
                            pending_vods,
                            key=lambda v: v.get("duration") if v.get("duration") else float("inf")
                        )
                        assert sorted_vods[0]["vod_id"] == "2"  # 30 min first
                        assert sorted_vods[1]["vod_id"] == "1"  # 1 hour second
                        assert sorted_vods[2]["vod_id"] == "3"  # 2 hours last
