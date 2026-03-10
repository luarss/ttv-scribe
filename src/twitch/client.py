"""Twitch API client"""
import time
import logging
from typing import Optional
import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)


class TwitchClient:
    """Client for Twitch API interaction"""

    BASE_URL = "https://api.twitch.tv/helix"

    def __init__(self):
        self.settings = get_settings()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._client = httpx.Client(timeout=30.0)

    def _get_access_token(self) -> str:
        """Get OAuth access token using client credentials flow"""
        # Check if current token is still valid
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        # Request new token
        response = self._client.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": self.settings.twitch_client_id,
                "client_secret": self.settings.twitch_client_secret,
                "grant_type": "client_credentials",
            },
        )
        response.raise_for_status()
        data = response.json()

        self._access_token = data["access_token"]
        # Set expiry 60 seconds before actual expiry to be safe
        self._token_expires_at = time.time() + data["expires_in"] - 60

        logger.info("Obtained new Twitch access token")
        return self._access_token

    def _get_headers(self) -> dict:
        """Get headers for API requests"""
        return {
            "Client-ID": self.settings.twitch_client_id,
            "Authorization": f"Bearer {self._get_access_token()}",
        }

    def get_user_by_username(self, username: str) -> Optional[dict]:
        """Get Twitch user by username"""
        response = self._client.get(
            f"{self.BASE_URL}/users",
            headers=self._get_headers(),
            params={"login": username},
        )
        response.raise_for_status()
        data = response.json()

        users = data.get("data", [])
        if users:
            return users[0]
        return None

    def get_vods_by_user(self, user_id: str, first: int = 20) -> list[dict]:
        """Get VODs for a Twitch user"""
        response = self._client.get(
            f"{self.BASE_URL}/videos",
            headers=self._get_headers(),
            params={"user_id": user_id, "first": first},
        )
        response.raise_for_status()
        data = response.json()

        return data.get("data", [])

    def get_video_by_id(self, video_id: str) -> Optional[dict]:
        """Get a specific Twitch VOD by ID"""
        response = self._client.get(
            f"{self.BASE_URL}/videos",
            headers=self._get_headers(),
            params={"id": video_id},
        )
        response.raise_for_status()
        data = response.json()

        videos = data.get("data", [])
        if videos:
            return videos[0]
        return None

    def close(self):
        """Close the HTTP client"""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()