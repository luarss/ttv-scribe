"""Bilibili API client

No authentication required for public videos.
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class BilibiliClient:
    """Client for Bilibili API interaction (no auth required for public content)"""

    BASE_URL = "https://api.bilibili.com"

    def __init__(self):
        self._client = httpx.Client(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.bilibili.com",
            },
        )

    def get_user_by_username(self, username: str) -> Optional[dict]:
        """Search for Bilibili user by username

        Note: Search may not return exact match. For reliability,
        users should provide the mid (user ID) directly.

        Args:
            username: The username to search for

        Returns:
            Dict with 'id' (mid as str) and 'name' if found, None otherwise
        """
        response = self._client.get(
            f"{self.BASE_URL}/x/web-interface/search/type",
            params={"search_type": "bili_user", "keyword": username},
        )
        response.raise_for_status()
        data = response.json()

        users = data.get("data", {}).get("result", [])
        if users:
            # Return first match (most relevant)
            user = users[0]
            return {"id": str(user["mid"]), "name": user["uname"]}
        return None

    def get_videos_by_mid(
        self, mid: str, page: int = 1, page_size: int = 50
    ) -> list[dict]:
        """Get videos for a Bilibili user by their mid (user ID)

        Args:
            mid: Bilibili user ID (member ID)
            page: Page number (1-indexed)
            page_size: Number of videos per page (max 50)

        Returns:
            List of video dicts with keys: bvid, title, duration, created, etc.
        """
        response = self._client.get(
            f"{self.BASE_URL}/x/space/wbi/arc/search",
            params={"mid": mid, "pn": page, "ps": page_size},
        )
        response.raise_for_status()
        data = response.json()

        videos = data.get("data", {}).get("list", {}).get("vlist", [])
        return videos

    def get_video_by_bvid(self, bvid: str) -> Optional[dict]:
        """Get a specific Bilibili video by bvid

        Args:
            bvid: Bilibili video ID (e.g., BV1xx411c7mD)

        Returns:
            Video info dict if found, None otherwise
        """
        response = self._client.get(
            f"{self.BASE_URL}/x/web-interface/view",
            params={"bvid": bvid},
        )
        response.raise_for_status()
        data = response.json()

        if data.get("data"):
            return data["data"]
        return None

    def close(self):
        """Close the HTTP client"""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
