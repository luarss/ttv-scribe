"""Tests for YouTube Data API v3 client"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.youtube.client import YouTubeClient


class TestParseIso8601Duration:
    """Tests for ISO 8601 duration parsing"""

    def test_hours_minutes_seconds(self):
        assert YouTubeClient._parse_iso8601_duration("PT2H30M15S") == 9015

    def test_hours_only(self):
        assert YouTubeClient._parse_iso8601_duration("PT1H") == 3600

    def test_minutes_only(self):
        assert YouTubeClient._parse_iso8601_duration("PT45M") == 2700

    def test_seconds_only(self):
        assert YouTubeClient._parse_iso8601_duration("PT30S") == 30

    def test_hours_and_minutes(self):
        assert YouTubeClient._parse_iso8601_duration("PT1H30M") == 5400

    def test_minutes_and_seconds(self):
        assert YouTubeClient._parse_iso8601_duration("PT5M30S") == 330

    def test_zero_duration(self):
        assert YouTubeClient._parse_iso8601_duration("PT0S") == 0

    def test_days_component(self):
        assert YouTubeClient._parse_iso8601_duration("P1DT2H30M15S") == 95415

    def test_empty_string(self):
        assert YouTubeClient._parse_iso8601_duration("") == 0

    def test_invalid_format(self):
        assert YouTubeClient._parse_iso8601_duration("invalid") == 0


class TestGetChannelByHandle:
    """Tests for get_channel_by_handle"""

    def test_successful_lookup(self, mock_settings, mock_youtube_response):
        with patch("src.youtube.client.get_settings", return_value=mock_settings):
            client = YouTubeClient()
            with patch.object(client._client, "get") as mock_get:
                mock_get.return_value = httpx.Response(
                    200,
                    json=mock_youtube_response["channel_by_handle"],
                    request=httpx.Request("GET", "http://test"),
                )
                result = client.get_channel_by_handle("karlrock")

                assert result is not None
                assert result["id"] == "UCtestChannelId123"
                assert result["uploads_playlist_id"] == "UUtestChannelId123"
                assert result["title"] == "Test Channel"
                client.close()

    def test_not_found(self, mock_settings):
        with patch("src.youtube.client.get_settings", return_value=mock_settings):
            client = YouTubeClient()
            with patch.object(client._client, "get") as mock_get:
                mock_get.return_value = httpx.Response(
                    200,
                    json={"items": []},
                    request=httpx.Request("GET", "http://test"),
                )
                result = client.get_channel_by_handle("nonexistent")
                assert result is None
                client.close()


class TestGetChannelById:
    """Tests for get_channel_by_id"""

    def test_successful_lookup(self, mock_settings, mock_youtube_response):
        with patch("src.youtube.client.get_settings", return_value=mock_settings):
            client = YouTubeClient()
            with patch.object(client._client, "get") as mock_get:
                mock_get.return_value = httpx.Response(
                    200,
                    json=mock_youtube_response["channel_by_id"],
                    request=httpx.Request("GET", "http://test"),
                )
                result = client.get_channel_by_id("UCtestChannelId123")

                assert result is not None
                assert result["id"] == "UCtestChannelId123"
                assert result["uploads_playlist_id"] == "UUtestChannelId123"
                client.close()

    def test_not_found(self, mock_settings):
        with patch("src.youtube.client.get_settings", return_value=mock_settings):
            client = YouTubeClient()
            with patch.object(client._client, "get") as mock_get:
                mock_get.return_value = httpx.Response(
                    200,
                    json={"items": []},
                    request=httpx.Request("GET", "http://test"),
                )
                result = client.get_channel_by_id("UCnonexistent")
                assert result is None
                client.close()


class TestGetRecentVideos:
    """Tests for get_recent_videos"""

    def test_successful_retrieval(self, mock_settings, mock_youtube_response):
        with patch("src.youtube.client.get_settings", return_value=mock_settings):
            client = YouTubeClient()
            with patch.object(client._client, "get") as mock_get:
                mock_get.return_value = httpx.Response(
                    200,
                    json=mock_youtube_response["playlist_items"],
                    request=httpx.Request("GET", "http://test"),
                )
                videos = client.get_recent_videos("UUtestChannelId123")

                assert len(videos) == 2
                assert videos[0]["video_id"] == "dQw4w9WgXcQ"
                assert videos[0]["title"] == "India Travel Day 1"
                assert videos[0]["published_at"] == "2024-01-15T12:00:00Z"
                assert videos[1]["video_id"] == "abc123def45"
                client.close()

    def test_empty_response(self, mock_settings):
        with patch("src.youtube.client.get_settings", return_value=mock_settings):
            client = YouTubeClient()
            with patch.object(client._client, "get") as mock_get:
                mock_get.return_value = httpx.Response(
                    200,
                    json={"items": []},
                    request=httpx.Request("GET", "http://test"),
                )
                videos = client.get_recent_videos("UUtestChannelId123")
                assert videos == []
                client.close()


class TestGetVideosDetails:
    """Tests for get_videos_details"""

    def test_batch_details(self, mock_settings, mock_youtube_response):
        with patch("src.youtube.client.get_settings", return_value=mock_settings):
            client = YouTubeClient()
            with patch.object(client._client, "get") as mock_get:
                mock_get.return_value = httpx.Response(
                    200,
                    json=mock_youtube_response["videos_details"],
                    request=httpx.Request("GET", "http://test"),
                )
                videos = client.get_videos_details(
                    ["dQw4w9WgXcQ", "abc123def45"]
                )

                assert len(videos) == 2
                assert videos[0]["id"] == "dQw4w9WgXcQ"
                assert videos[0]["duration"] == 9015  # PT2H30M15S
                assert videos[1]["id"] == "abc123def45"
                assert videos[1]["duration"] == 2700  # PT45M
                client.close()

    def test_empty_input(self, mock_settings):
        with patch("src.youtube.client.get_settings", return_value=mock_settings):
            client = YouTubeClient()
            result = client.get_videos_details([])
            assert result == []
            client.close()


class TestGetVideoById:
    """Tests for get_video_by_id"""

    def test_found(self, mock_settings, mock_youtube_response):
        with patch("src.youtube.client.get_settings", return_value=mock_settings):
            client = YouTubeClient()
            with patch.object(client._client, "get") as mock_get:
                # Return only the first video
                response_data = {
                    "items": [mock_youtube_response["videos_details"]["items"][0]]
                }
                mock_get.return_value = httpx.Response(
                    200,
                    json=response_data,
                    request=httpx.Request("GET", "http://test"),
                )
                result = client.get_video_by_id("dQw4w9WgXcQ")

                assert result is not None
                assert result["id"] == "dQw4w9WgXcQ"
                assert result["duration"] == 9015
                client.close()

    def test_not_found(self, mock_settings):
        with patch("src.youtube.client.get_settings", return_value=mock_settings):
            client = YouTubeClient()
            with patch.object(client._client, "get") as mock_get:
                mock_get.return_value = httpx.Response(
                    200,
                    json={"items": []},
                    request=httpx.Request("GET", "http://test"),
                )
                result = client.get_video_by_id("nonexistent")
                assert result is None
                client.close()


class TestContextManager:
    """Tests for context manager pattern"""

    def test_enter_returns_self(self, mock_settings):
        with patch("src.youtube.client.get_settings", return_value=mock_settings):
            client = YouTubeClient()
            assert client.__enter__() is client
            client.close()

    def test_exit_closes_client(self, mock_settings):
        with patch("src.youtube.client.get_settings", return_value=mock_settings):
            client = YouTubeClient()
            with patch.object(client._client, "close") as mock_close:
                client.__exit__(None, None, None)
                mock_close.assert_called_once()
