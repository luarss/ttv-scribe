"""Tests for Twitch API client"""

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from src.twitch.client import TwitchClient


class TestTwitchClientInit:
    """Tests for TwitchClient initialization"""

    def test_init_creates_httpx_client(self, mock_settings):
        """Test that init creates an httpx client"""
        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            assert client._client is not None
            assert isinstance(client._client, httpx.Client)
            client.close()

    def test_init_loads_settings(self, mock_settings):
        """Test that init loads settings"""
        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            assert client.settings.twitch_client_id == "test_client_id"
            client.close()

    def test_init_no_token(self, mock_settings):
        """Test that init doesn't fetch token immediately"""
        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            assert client._access_token is None
            assert client._token_expires_at == 0
            client.close()


class TestGetAccessToken:
    """Tests for OAuth token acquisition"""

    @respx.mock
    def test_first_call_fetches_token(self, mock_settings, mock_twitch_response):
        """Test that first call fetches a new token"""
        respx.post("https://id.twitch.tv/oauth2/token").mock(
            return_value=httpx.Response(200, json=mock_twitch_response["token"])
        )

        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            token = client._get_access_token()

            assert token == "test_token_123"
            assert client._access_token == "test_token_123"
            client.close()

    @respx.mock
    def test_caches_token(self, mock_settings, mock_twitch_response):
        """Test that token is cached and reused"""
        respx.post("https://id.twitch.tv/oauth2/token").mock(
            return_value=httpx.Response(200, json=mock_twitch_response["token"])
        )

        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()

            # First call
            token1 = client._get_access_token()
            # Second call - should use cache
            token2 = client._get_access_token()

            assert token1 == token2
            # Should only have called the API once
            assert respx.calls.call_count == 1
            client.close()

    @respx.mock
    def test_refreshes_expired_token(self, mock_settings, mock_twitch_response):
        """Test that expired token is refreshed"""
        # First token
        respx.post("https://id.twitch.tv/oauth2/token").mock(
            return_value=httpx.Response(200, json={
                "access_token": "old_token",
                "expires_in": 100,
                "token_type": "bearer"
            })
        )

        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()

            # Get initial token
            token1 = client._get_access_token()
            assert token1 == "old_token"

            # Expire the token
            client._token_expires_at = time.time() - 1

            # Mock new token response
            respx.post("https://id.twitch.tv/oauth2/token").mock(
                return_value=httpx.Response(200, json={
                    "access_token": "new_token",
                    "expires_in": 3600,
                    "token_type": "bearer"
                })
            )

            # Get token again - should refresh
            token2 = client._get_access_token()
            assert token2 == "new_token"
            client.close()

    @respx.mock
    def test_token_request_includes_credentials(self, mock_settings):
        """Test that token request includes client credentials"""
        route = respx.post("https://id.twitch.tv/oauth2/token").mock(
            return_value=httpx.Response(200, json={
                "access_token": "test_token",
                "expires_in": 3600,
                "token_type": "bearer"
            })
        )

        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            client._get_access_token()

            request = route.calls.last.request
            assert "client_id=test_client_id" in str(request.content)
            assert "client_secret=test_client_secret" in str(request.content)
            client.close()


class TestGetHeaders:
    """Tests for API request headers"""

    @respx.mock
    def test_headers_include_authorization(self, mock_settings, mock_twitch_response):
        """Test that headers include Bearer token"""
        respx.post("https://id.twitch.tv/oauth2/token").mock(
            return_value=httpx.Response(200, json=mock_twitch_response["token"])
        )

        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            headers = client._get_headers()

            assert headers["Authorization"] == "Bearer test_token_123"
            client.close()

    def test_headers_include_client_id(self, mock_settings):
        """Test that headers include Client-ID"""
        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            with respx.mock:
                respx.post("https://id.twitch.tv/oauth2/token").mock(
                    return_value=httpx.Response(200, json={"access_token": "token", "expires_in": 3600, "token_type": "bearer"})
                )
                client = TwitchClient()
                headers = client._get_headers()

                assert headers["Client-ID"] == "test_client_id"
                client.close()


class TestGetUserByUsername:
    """Tests for get_user_by_username method"""

    @respx.mock
    def test_success_response(self, mock_settings, mock_twitch_response):
        """Test successful user lookup"""
        respx.post("https://id.twitch.tv/oauth2/token").mock(
            return_value=httpx.Response(200, json=mock_twitch_response["token"])
        )
        respx.get("https://api.twitch.tv/helix/users").mock(
            return_value=httpx.Response(200, json={"data": [mock_twitch_response["user"]]})
        )

        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            user = client.get_user_by_username("testuser")

            assert user is not None
            assert user["id"] == "123456"
            assert user["login"] == "testuser"
            client.close()

    @respx.mock
    def test_user_not_found(self, mock_settings, mock_twitch_response):
        """Test when user is not found"""
        respx.post("https://id.twitch.tv/oauth2/token").mock(
            return_value=httpx.Response(200, json=mock_twitch_response["token"])
        )
        respx.get("https://api.twitch.tv/helix/users").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            user = client.get_user_by_username("nonexistent")

            assert user is None
            client.close()

    @respx.mock
    def test_api_error(self, mock_settings, mock_twitch_response):
        """Test handling of API error"""
        respx.post("https://id.twitch.tv/oauth2/token").mock(
            return_value=httpx.Response(200, json=mock_twitch_response["token"])
        )
        respx.get("https://api.twitch.tv/helix/users").mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )

        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            with pytest.raises(httpx.HTTPStatusError):
                client.get_user_by_username("testuser")
            client.close()


class TestGetVodsByUser:
    """Tests for get_vods_by_user method"""

    @respx.mock
    def test_success_response(self, mock_settings, mock_twitch_response):
        """Test successful VOD list retrieval"""
        respx.post("https://id.twitch.tv/oauth2/token").mock(
            return_value=httpx.Response(200, json=mock_twitch_response["token"])
        )
        respx.get("https://api.twitch.tv/helix/videos").mock(
            return_value=httpx.Response(200, json={"data": [mock_twitch_response["vod"]]})
        )

        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            vods = client.get_vods_by_user("123456")

            assert len(vods) == 1
            assert vods[0]["id"] == "1234567890"
            client.close()

    @respx.mock
    def test_empty_response(self, mock_settings, mock_twitch_response):
        """Test when user has no VODs"""
        respx.post("https://id.twitch.tv/oauth2/token").mock(
            return_value=httpx.Response(200, json=mock_twitch_response["token"])
        )
        respx.get("https://api.twitch.tv/helix/videos").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            vods = client.get_vods_by_user("123456")

            assert vods == []
            client.close()

    @respx.mock
    def test_pagination_parameter(self, mock_settings, mock_twitch_response):
        """Test that pagination parameter is passed"""
        respx.post("https://id.twitch.tv/oauth2/token").mock(
            return_value=httpx.Response(200, json=mock_twitch_response["token"])
        )
        route = respx.get("https://api.twitch.tv/helix/videos").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            client.get_vods_by_user("123456", first=50)

            request = route.calls.last.request
            assert "first=50" in str(request.url)
            client.close()


class TestGetVideoById:
    """Tests for get_video_by_id method"""

    @respx.mock
    def test_success_response(self, mock_settings, mock_twitch_response):
        """Test successful video lookup"""
        respx.post("https://id.twitch.tv/oauth2/token").mock(
            return_value=httpx.Response(200, json=mock_twitch_response["token"])
        )
        respx.get("https://api.twitch.tv/helix/videos").mock(
            return_value=httpx.Response(200, json={"data": [mock_twitch_response["vod"]]})
        )

        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            video = client.get_video_by_id("1234567890")

            assert video is not None
            assert video["id"] == "1234567890"
            client.close()

    @respx.mock
    def test_video_not_found(self, mock_settings, mock_twitch_response):
        """Test when video is not found"""
        respx.post("https://id.twitch.tv/oauth2/token").mock(
            return_value=httpx.Response(200, json=mock_twitch_response["token"])
        )
        respx.get("https://api.twitch.tv/helix/videos").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            video = client.get_video_by_id("nonexistent")

            assert video is None
            client.close()


class TestContextManager:
    """Tests for context manager behavior"""

    def test_enter_returns_self(self, mock_settings):
        """Test that __enter__ returns the client"""
        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            with TwitchClient() as client:
                assert client is not None

    def test_exit_closes_client(self, mock_settings):
        """Test that __exit__ calls close()"""
        with patch("src.twitch.client.get_settings", return_value=mock_settings):
            client = TwitchClient()
            mock_close = MagicMock()
            client.close = mock_close

            client.__exit__(None, None, None)
            mock_close.assert_called_once()
