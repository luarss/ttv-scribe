"""Tests for Kick.com API client"""

from unittest.mock import MagicMock, patch

import pytest

from src.kick.client import KickClient


class TestKickClientInit:
    """Tests for KickClient initialization"""

    def test_creates_session_with_impersonate(self):
        """Test that session is created with chrome impersonation"""
        with patch("curl_cffi.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            client = KickClient()

            mock_session_class.assert_called_once()
            assert mock_session.impersonate == "chrome131"

    def test_sets_default_headers(self):
        """Test that User-Agent and Accept headers are set"""
        with patch("curl_cffi.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            KickClient()

            mock_session.headers.update.assert_called_once()
            headers = mock_session.headers.update.call_args[0][0]
            assert "User-Agent" in headers
            assert "Accept" in headers
            assert headers["Accept"] == "application/json"


class TestGetChannelBySlug:
    """Tests for get_channel_by_slug"""

    def test_success_response(self):
        """Test successful channel lookup returns dict"""
        with patch("curl_cffi.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"id": 123, "slug": "testuser"}
            mock_session.get.return_value = mock_response

            client = KickClient()
            channel = client.get_channel_by_slug("testuser")

            assert channel == {"id": 123, "slug": "testuser"}
            mock_session.get.assert_called_with(
                "https://kick.com/api/v2/channels/testuser"
            )
            client.close()

    def test_channel_not_found(self):
        """Test that 404 returns None"""
        with patch("curl_cffi.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_session.get.return_value = mock_response

            client = KickClient()
            channel = client.get_channel_by_slug("nonexistent")

            assert channel is None
            client.close()

    def test_api_error_raises(self):
        """Test that non-404 errors raise"""
        with patch("curl_cffi.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.raise_for_status.side_effect = Exception("Server Error")
            mock_session.get.return_value = mock_response

            client = KickClient()

            with pytest.raises(Exception, match="Server Error"):
                client.get_channel_by_slug("testuser")

            client.close()


class TestGetVodsBySlug:
    """Tests for get_vods_by_slug"""

    def test_returns_list_when_api_returns_bare_list(self):
        """Test that bare list response is returned directly"""
        with patch("curl_cffi.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            vods = [
                {"id": "uuid-1", "title": "VOD 1", "duration": 3600},
                {"id": "uuid-2", "title": "VOD 2", "duration": 1800},
            ]
            mock_response = MagicMock()
            mock_response.json.return_value = vods
            mock_session.get.return_value = mock_response

            client = KickClient()
            result = client.get_vods_by_slug("testuser")

            assert result == vods
            assert len(result) == 2
            mock_session.get.assert_called_with(
                "https://kick.com/api/v2/channels/testuser/videos"
            )
            client.close()

    def test_returns_videos_from_dict_wrapper(self):
        """Test that dict with 'videos' key is unwrapped"""
        with patch("curl_cffi.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            vods = [{"id": "uuid-1", "title": "VOD 1"}]
            mock_response = MagicMock()
            mock_response.json.return_value = {"videos": vods}
            mock_session.get.return_value = mock_response

            client = KickClient()
            result = client.get_vods_by_slug("testuser")

            assert result == vods
            client.close()

    def test_returns_data_from_alt_wrapper_key(self):
        """Test that dict with 'data' key is unwrapped"""
        with patch("curl_cffi.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            vods = [{"id": "uuid-1", "title": "VOD 1"}]
            mock_response = MagicMock()
            mock_response.json.return_value = {"data": vods}
            mock_session.get.return_value = mock_response

            client = KickClient()
            result = client.get_vods_by_slug("testuser")

            assert result == vods
            client.close()

    def test_returns_empty_for_unknown_dict(self):
        """Test that unknown dict shape returns empty list"""
        with patch("curl_cffi.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            mock_response = MagicMock()
            mock_response.json.return_value = {"unknown_key": "value"}
            mock_session.get.return_value = mock_response

            client = KickClient()
            result = client.get_vods_by_slug("testuser")

            assert result == []
            client.close()


class TestGetVideoByUuid:
    """Tests for get_video_by_uuid"""

    def test_success_response(self):
        """Test successful video lookup"""
        with patch("curl_cffi.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            video = {"id": "uuid-1", "title": "Test VOD", "duration": 3600}
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = video
            mock_session.get.return_value = mock_response

            client = KickClient()
            result = client.get_video_by_uuid("uuid-1")

            assert result == video
            mock_session.get.assert_called_with(
                "https://kick.com/api/v2/videos/uuid-1"
            )
            client.close()

    def test_video_not_found(self):
        """Test that 404 returns None"""
        with patch("curl_cffi.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_session.get.return_value = mock_response

            client = KickClient()
            result = client.get_video_by_uuid("nonexistent")

            assert result is None
            client.close()


class TestContextManager:
    """Tests for context manager behavior"""

    def test_enter_returns_self(self):
        """Test that __enter__ returns the client instance"""
        with patch("curl_cffi.requests.Session") as mock_session_class:
            mock_session_class.return_value = MagicMock()

            client = KickClient()
            result = client.__enter__()

            assert result is client
            client.close()

    def test_exit_closes_session(self):
        """Test that __exit__ closes the session"""
        with patch("curl_cffi.requests.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            client = KickClient()
            client.__exit__(None, None, None)

            mock_session.close.assert_called_once()
