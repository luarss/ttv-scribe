"""Tests for VOD monitoring"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call

import pytest

from src.monitor import (
    check_for_new_vods,
    _check_streamer_vods,
    add_streamers_to_track,
    get_streamer,
)
from src.state import VodStatus, VodRecord, StreamerRecord


class TestDurationParsing:
    """Tests for Twitch duration parsing in _check_streamer_vods"""

    def test_parse_hours_minutes_seconds(self, mock_state_manager):
        """Test parsing '2h3m10s' format"""
        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.TwitchClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_user_by_username.return_value = {"id": "123"}
                mock_client.get_vods_by_user.return_value = [{
                    "id": "vod1",
                    "title": "Test",
                    "created_at": "2024-01-01T00:00:00Z",  # Old enough
                    "duration": "2h3m10s",  # 2*3600 + 3*60 + 10 = 7390 seconds
                }]

                count = _check_streamer_vods("testuser", "twitch", None, None, None, max_duration_minutes=None, min_days_old=0)

                assert count == 1
                vod = mock_state_manager.get_vod("vod1")
                assert vod.duration == 7390

    def test_parse_minutes_seconds(self, mock_state_manager):
        """Test parsing '45m30s' format"""
        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.TwitchClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_user_by_username.return_value = {"id": "123"}
                mock_client.get_vods_by_user.return_value = [{
                    "id": "vod1",
                    "title": "Test",
                    "created_at": "2024-01-01T00:00:00Z",
                    "duration": "45m30s",  # 45*60 + 30 = 2730 seconds
                }]

                count = _check_streamer_vods("testuser", "twitch", None, None, None, max_duration_minutes=None, min_days_old=0)

                assert count == 1
                vod = mock_state_manager.get_vod("vod1")
                assert vod.duration == 2730

    def test_parse_seconds_only(self, mock_state_manager):
        """Test parsing '30s' format"""
        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.TwitchClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_user_by_username.return_value = {"id": "123"}
                mock_client.get_vods_by_user.return_value = [{
                    "id": "vod1",
                    "title": "Test",
                    "created_at": "2024-01-01T00:00:00Z",
                    "duration": "30s",
                }]

                count = _check_streamer_vods("testuser", "twitch", None, None, None, max_duration_minutes=None, min_days_old=0)

                assert count == 1
                vod = mock_state_manager.get_vod("vod1")
                assert vod.duration == 30

    def test_parse_hours_only(self, mock_state_manager):
        """Test parsing '1h' format"""
        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.TwitchClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_user_by_username.return_value = {"id": "123"}
                mock_client.get_vods_by_user.return_value = [{
                    "id": "vod1",
                    "title": "Test",
                    "created_at": "2024-01-01T00:00:00Z",
                    "duration": "1h",
                }]

                count = _check_streamer_vods("testuser", "twitch", None, None, None, max_duration_minutes=None, min_days_old=0)

                assert count == 1
                vod = mock_state_manager.get_vod("vod1")
                assert vod.duration == 3600


class TestCheckStreamerVods:
    """Tests for _check_streamer_vods function"""

    def test_filters_by_max_duration(self, mock_state_manager):
        """Test that VODs longer than max_duration are skipped"""
        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.TwitchClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_user_by_username.return_value = {"id": "123"}
                mock_client.get_vods_by_user.return_value = [
                    {
                        "id": "vod1",
                        "title": "Short",
                        "created_at": "2024-01-01T00:00:00Z",
                        "duration": "30m0s",  # 30 min
                    },
                    {
                        "id": "vod2",
                        "title": "Long",
                        "created_at": "2024-01-01T00:00:00Z",
                        "duration": "2h0m0s",  # 2 hours
                    },
                ]

                count = _check_streamer_vods(
                    "testuser", "twitch", None, None, None,
                    max_duration_minutes=60,  # 1 hour max
                    min_days_old=0
                )

                assert count == 1
                assert mock_state_manager.get_vod("vod1") is not None
                assert mock_state_manager.get_vod("vod2") is None

    def test_filters_by_min_days_old(self, mock_state_manager):
        """Test that VODs too recent are skipped"""
        recent_time = datetime.now(timezone.utc) - timedelta(days=1)
        old_time = datetime.now(timezone.utc) - timedelta(days=5)

        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.TwitchClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_user_by_username.return_value = {"id": "123"}
                mock_client.get_vods_by_user.return_value = [
                    {
                        "id": "vod1",
                        "title": "Recent",
                        "created_at": recent_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "duration": "30m0s",
                    },
                    {
                        "id": "vod2",
                        "title": "Old",
                        "created_at": old_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "duration": "30m0s",
                    },
                ]

                count = _check_streamer_vods(
                    "testuser", "twitch", None, None, None,
                    max_duration_minutes=None,
                    min_days_old=3
                )

                assert count == 1
                assert mock_state_manager.get_vod("vod1") is None
                assert mock_state_manager.get_vod("vod2") is not None

    def test_creates_vod_record(self, mock_state_manager):
        """Test that VodRecord is created with correct fields"""
        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.TwitchClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_user_by_username.return_value = {"id": "123"}
                mock_client.get_vods_by_user.return_value = [{
                    "id": "vod1",
                    "title": "Test Stream",
                    "created_at": "2024-01-15T12:00:00Z",
                    "duration": "1h30m0s",
                }]

                _check_streamer_vods("testuser", "twitch", None, None, None, max_duration_minutes=None, min_days_old=0)

                vod = mock_state_manager.get_vod("vod1")
                assert vod is not None
                assert vod.vod_id == "vod1"
                assert vod.streamer == "testuser"
                assert vod.title == "Test Stream"
                assert vod.duration == 5400  # 1.5 hours
                assert vod.status == VodStatus.PENDING.value

    def test_uses_existing_twitch_id(self, mock_state_manager):
        """Test that existing twitch_id is used instead of fetching"""
        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.TwitchClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_vods_by_user.return_value = [{
                    "id": "vod1",
                    "title": "Test",
                    "created_at": "2024-01-01T00:00:00Z",
                    "duration": "30m0s",
                }]

                _check_streamer_vods("testuser", "twitch", "existing_id", None, None, max_duration_minutes=None, min_days_old=0)

                # Should not call get_user_by_username since we have twitch_id
                mock_client.get_user_by_username.assert_not_called()
                mock_client.get_vods_by_user.assert_called_once_with("existing_id")

    def test_skips_existing_vods(self, mock_state_manager):
        """Test that already-tracked VODs are not re-added"""
        # Pre-add a VOD
        mock_state_manager.add_vod(VodRecord(vod_id="vod1", streamer="testuser"))

        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.TwitchClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_user_by_username.return_value = {"id": "123"}
                mock_client.get_vods_by_user.return_value = [{
                    "id": "vod1",
                    "title": "Test",
                    "created_at": "2024-01-01T00:00:00Z",
                    "duration": "30m0s",
                }]

                count = _check_streamer_vods("testuser", "twitch", None, None, None, max_duration_minutes=None, min_days_old=0)

                assert count == 0  # No new VODs added


class TestCheckStreamerVodsErrors:
    """Tests for error handling in _check_streamer_vods"""

    def test_twitch_client_exception(self, mock_state_manager):
        """Test that TwitchClient exceptions are propagated"""
        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.TwitchClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(side_effect=Exception("API Error"))
                mock_client_class.return_value = mock_client

                with pytest.raises(Exception, match="API Error"):
                    _check_streamer_vods("testuser", "twitch", None, None, None, max_duration_minutes=None, min_days_old=0)

    def test_streamer_not_found(self, mock_state_manager):
        """Test handling when streamer is not found on Twitch"""
        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.TwitchClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_user_by_username.return_value = None

                count = _check_streamer_vods("nonexistent", "twitch", None, None, None, max_duration_minutes=None, min_days_old=0)

                assert count == 0

    def test_no_vods_returned(self, mock_state_manager):
        """Test handling when no VODs are returned"""
        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.TwitchClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_user_by_username.return_value = {"id": "123"}
                mock_client.get_vods_by_user.return_value = []

                count = _check_streamer_vods("testuser", "twitch", None, None, None, max_duration_minutes=None, min_days_old=0)

                assert count == 0


class TestCheckForNewVods:
    """Tests for check_for_new_vods function"""

    def test_no_streamers_returns_zero(self):
        """Test that check returns 0 when no streamers are tracked"""
        with patch("src.monitor.get_streamers", return_value=[]):
            count = check_for_new_vods()
            assert count == 0

    def test_processes_multiple_streamers(self, mock_state_manager):
        """Test that multiple streamers are processed"""
        with patch("src.monitor.get_streamers", return_value=[
            {"username": "user1", "platform": "twitch", "twitch_id": "1", "bilibili_mid": None},
            {"username": "user2", "platform": "twitch", "twitch_id": "2", "bilibili_mid": None},
        ]):
            with patch("src.monitor._check_streamer_vods", return_value=2) as mock_check:
                count = check_for_new_vods()

                assert count == 4  # 2 streamers * 2 VODs each
                assert mock_check.call_count == 2

    def test_respects_max_workers(self):
        """Test that max_workers parameter is used"""
        with patch("src.monitor.get_streamers", return_value=[
            {"username": f"user{i}", "twitch_id": str(i)} for i in range(10)
        ]):
            with patch("src.monitor.ThreadPoolExecutor") as mock_executor:
                mock_executor.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_executor.return_value.__exit__ = MagicMock(return_value=False)

                check_for_new_vods(max_workers=3)

                # Verify ThreadPoolExecutor was created with max_workers=3
                mock_executor.assert_called_once()
                call_kwargs = mock_executor.call_args[1]
                assert call_kwargs["max_workers"] == 3


class TestAddStreamersToTrack:
    """Tests for add_streamers_to_track function"""

    def test_adds_new_streamers(self, mock_state_manager):
        """Test adding new streamers to track"""
        with patch("src.monitor.get_streamer", side_effect=lambda u: None):
            with patch("src.monitor.add_streamer") as mock_add:
                count = add_streamers_to_track(["user1", "user2"])

                assert count == 2
                assert mock_add.call_count == 2

    def test_skips_existing_streamers(self, mock_state_manager):
        """Test that existing streamers are not re-added"""
        with patch("src.monitor.get_streamer", side_effect=lambda u: {"username": u} if u == "existing" else None):
            with patch("src.monitor.add_streamer") as mock_add:
                count = add_streamers_to_track(["existing", "new"])

                assert count == 1
                mock_add.assert_called_once_with("new")


class TestGetStreamer:
    """Tests for get_streamer function"""

    def test_returns_streamer_dict(self, mock_state_manager):
        """Test that streamer dict is returned"""
        mock_state_manager.add_streamer(StreamerRecord(username="testuser", twitch_id="123"))

        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            result = get_streamer("testuser")

            assert result is not None
            assert result["username"] == "testuser"
            assert result["twitch_id"] == "123"

    def test_returns_none_for_nonexistent(self, mock_state_manager):
        """Test that None is returned for nonexistent streamer"""
        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            result = get_streamer("nonexistent")

            assert result is None


class TestCheckYouTubeVods:
    """Tests for _check_youtube_vods function"""

    def test_creates_vod_records(self, mock_state_manager):
        """Test that VodRecords are created for YouTube videos"""
        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.YouTubeClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                # Channel lookup returns uploads playlist
                mock_client.get_channel_by_id.return_value = {
                    "id": "UCtestChannelId123",
                    "uploads_playlist_id": "UUtestChannelId123",
                    "title": "Test Channel",
                }

                # Recent videos from playlist
                mock_client.get_recent_videos.return_value = [
                    {
                        "video_id": "vid1",
                        "title": "India Travel Day 1",
                        "published_at": "2024-01-01T00:00:00Z",
                    },
                    {
                        "video_id": "vid2",
                        "title": "India Travel Day 2",
                        "published_at": "2024-01-02T00:00:00Z",
                    },
                ]

                # Video details with durations
                mock_client.get_videos_details.return_value = [
                    {
                        "id": "vid1",
                        "title": "India Travel Day 1",
                        "duration": 3600,
                        "published_at": "2024-01-01T00:00:00Z",
                    },
                    {
                        "id": "vid2",
                        "title": "India Travel Day 2",
                        "duration": 1800,
                        "published_at": "2024-01-02T00:00:00Z",
                    },
                ]

                count = _check_streamer_vods(
                    "testchannel",
                    "youtube",
                    None,
                    None,
                    "UCtestChannelId123",
                    max_duration_minutes=None,
                    min_days_old=0,
                )

                assert count == 2
                vod1 = mock_state_manager.get_vod("vid1")
                assert vod1 is not None
                assert vod1.streamer == "testchannel"
                assert vod1.platform == "youtube"
                assert vod1.duration == 3600
                vod2 = mock_state_manager.get_vod("vid2")
                assert vod2 is not None
                assert vod2.duration == 1800

    def test_filters_by_max_duration(self, mock_state_manager):
        """Test that YouTube VODs longer than max_duration are skipped"""
        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.YouTubeClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_channel_by_id.return_value = {
                    "id": "UCtest",
                    "uploads_playlist_id": "UUtest",
                }
                mock_client.get_recent_videos.return_value = [
                    {"video_id": "short", "title": "Short", "published_at": "2024-01-01T00:00:00Z"},
                    {"video_id": "long", "title": "Long", "published_at": "2024-01-01T00:00:00Z"},
                ]
                mock_client.get_videos_details.return_value = [
                    {"id": "short", "title": "Short", "duration": 1800, "published_at": "2024-01-01T00:00:00Z"},
                    {"id": "long", "title": "Long", "duration": 7200, "published_at": "2024-01-01T00:00:00Z"},
                ]

                count = _check_streamer_vods(
                    "testchannel", "youtube", None, None, "UCtest",
                    max_duration_minutes=60, min_days_old=0,
                )

                assert count == 1
                assert mock_state_manager.get_vod("short") is not None
                assert mock_state_manager.get_vod("long") is None

    def test_filters_by_min_days_old(self, mock_state_manager):
        """Test that recent YouTube videos are skipped"""
        recent_time = datetime.now(timezone.utc) - timedelta(days=1)
        old_time = datetime.now(timezone.utc) - timedelta(days=5)

        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.YouTubeClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_channel_by_id.return_value = {
                    "id": "UCtest",
                    "uploads_playlist_id": "UUtest",
                }
                mock_client.get_recent_videos.return_value = [
                    {
                        "video_id": "recent",
                        "title": "Recent",
                        "published_at": recent_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                    {
                        "video_id": "old",
                        "title": "Old",
                        "published_at": old_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                ]
                mock_client.get_videos_details.return_value = [
                    {
                        "id": "recent",
                        "title": "Recent",
                        "duration": 1800,
                        "published_at": recent_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                    {
                        "id": "old",
                        "title": "Old",
                        "duration": 1800,
                        "published_at": old_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                ]

                count = _check_streamer_vods(
                    "testchannel", "youtube", None, None, "UCtest",
                    max_duration_minutes=None, min_days_old=3,
                )

                assert count == 1
                assert mock_state_manager.get_vod("recent") is None
                assert mock_state_manager.get_vod("old") is not None

    def test_skips_existing_vods(self, mock_state_manager):
        """Test that already-tracked YouTube VODs are not re-added"""
        mock_state_manager.add_vod(VodRecord(vod_id="vid1", streamer="testchannel"))

        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.YouTubeClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_channel_by_id.return_value = {
                    "id": "UCtest",
                    "uploads_playlist_id": "UUtest",
                }
                mock_client.get_recent_videos.return_value = [
                    {"video_id": "vid1", "title": "Existing", "published_at": "2024-01-01T00:00:00Z"},
                    {"video_id": "vid2", "title": "New", "published_at": "2024-01-01T00:00:00Z"},
                ]
                mock_client.get_videos_details.return_value = [
                    {"id": "vid1", "title": "Existing", "duration": 1800, "published_at": "2024-01-01T00:00:00Z"},
                    {"id": "vid2", "title": "New", "duration": 1800, "published_at": "2024-01-01T00:00:00Z"},
                ]

                count = _check_streamer_vods(
                    "testchannel", "youtube", None, None, "UCtest",
                    max_duration_minutes=None, min_days_old=0,
                )

                assert count == 1

    def test_channel_lookup_by_handle(self, mock_state_manager):
        """Test that channel is looked up by handle when no channel_id"""
        with patch("src.monitor.get_state_manager", return_value=mock_state_manager):
            with patch("src.monitor.YouTubeClient") as mock_client_class:
                mock_client = MagicMock()
                mock_client.__enter__ = MagicMock(return_value=mock_client)
                mock_client.__exit__ = MagicMock(return_value=False)
                mock_client_class.return_value = mock_client

                mock_client.get_channel_by_handle.return_value = {
                    "id": "UCfoundChannelId",
                    "uploads_playlist_id": "UUfoundChannelId",
                    "title": "Found Channel",
                }
                mock_client.get_recent_videos.return_value = []
                mock_client.get_videos_details.return_value = []

                _check_streamer_vods(
                    "karlrock", "youtube", None, None, None,
                    max_duration_minutes=None, min_days_old=0,
                )

                mock_client.get_channel_by_handle.assert_called_once_with("karlrock")

