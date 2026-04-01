"""YouTube Data API v3 client

Uses API key authentication for public content access.
Follows the same patterns as TwitchClient and BilibiliClient.
"""

import logging
import re
from typing import Optional

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)


class YouTubeClient:
    """Client for YouTube Data API v3 interaction"""

    BASE_URL = "https://www.googleapis.com/youtube/v3"

    def __init__(self):
        self.settings = get_settings()
        self._api_key = self.settings.youtube_api_key
        self._client = httpx.Client(timeout=30.0)

    def _get_params(self, **kwargs) -> dict:
        """Build query params with API key"""
        return {"key": self._api_key, **kwargs}

    @staticmethod
    def _parse_iso8601_duration(duration_str: str) -> int:
        """Parse ISO 8601 duration string to seconds.

        Handles formats like: PT2H30M15S, PT1H, PT45M, PT30S, PT0S
        Also handles day components: P1DT2H30M15S

        Returns:
            Duration in seconds (0 if parsing fails)
        """
        m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str)
        if not m:
            return 0
        days, hours, minutes, seconds = m.groups()
        total = (
            int(days or 0) * 86400
            + int(hours or 0) * 3600
            + int(minutes or 0) * 60
            + int(seconds or 0)
        )
        return total if total > 0 else 0

    def get_channel_by_handle(self, handle: str) -> Optional[dict]:
        """Look up a YouTube channel by its handle (e.g., 'karlrock' for @karlrock)

        Args:
            handle: YouTube handle without @ prefix

        Returns:
            Dict with 'id', 'uploads_playlist_id', 'title' if found, None otherwise
        """
        response = self._client.get(
            f"{self.BASE_URL}/channels",
            params=self._get_params(
                part="snippet,contentDetails",
                forHandle=handle,
            ),
        )
        response.raise_for_status()
        data = response.json()

        items = data.get("items", [])
        if not items:
            return None

        item = items[0]
        uploads_playlist_id = (
            item.get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads")
        )

        return {
            "id": item["id"],
            "uploads_playlist_id": uploads_playlist_id,
            "title": item.get("snippet", {}).get("title", ""),
        }

    def get_channel_by_id(self, channel_id: str) -> Optional[dict]:
        """Look up a YouTube channel by its channel ID

        Args:
            channel_id: YouTube channel ID (e.g., 'UCx5SbxogW3VGJ6BwYNc0ypQ')

        Returns:
            Dict with 'id', 'uploads_playlist_id', 'title' if found, None otherwise
        """
        response = self._client.get(
            f"{self.BASE_URL}/channels",
            params=self._get_params(
                part="snippet,contentDetails",
                id=channel_id,
            ),
        )
        response.raise_for_status()
        data = response.json()

        items = data.get("items", [])
        if not items:
            return None

        item = items[0]
        uploads_playlist_id = (
            item.get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads")
        )

        return {
            "id": item["id"],
            "uploads_playlist_id": uploads_playlist_id,
            "title": item.get("snippet", {}).get("title", ""),
        }

    def get_recent_videos(
        self, playlist_id: str, max_results: int = 50
    ) -> list[dict]:
        """Get recent videos from a channel's uploads playlist

        Args:
            playlist_id: The uploads playlist ID (starts with 'UU')
            max_results: Number of videos to return (max 50)

        Returns:
            List of dicts with 'video_id', 'title', 'published_at'
        """
        response = self._client.get(
            f"{self.BASE_URL}/playlistItems",
            params=self._get_params(
                part="snippet",
                playlistId=playlist_id,
                maxResults=max_results,
            ),
        )
        response.raise_for_status()
        data = response.json()

        videos = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            resource = snippet.get("resourceId", {})
            video_id = resource.get("videoId")
            if not video_id:
                continue

            videos.append(
                {
                    "video_id": video_id,
                    "title": snippet.get("title", ""),
                    "published_at": snippet.get("publishedAt", ""),
                }
            )

        return videos

    def get_videos_details(self, video_ids: list[str]) -> list[dict]:
        """Get details (including duration) for a batch of videos

        Args:
            video_ids: List of YouTube video IDs (max 50 per request)

        Returns:
            List of dicts with 'id', 'title', 'duration' (seconds), 'published_at'
        """
        if not video_ids:
            return []

        all_videos = []
        # Batch in groups of 50 (YouTube API limit)
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i : i + 50]
            response = self._client.get(
                f"{self.BASE_URL}/videos",
                params=self._get_params(
                    part="snippet,contentDetails",
                    id=",".join(batch),
                ),
            )
            response.raise_for_status()
            data = response.json()

            for item in data.get("items", []):
                duration_str = (
                    item.get("contentDetails", {}).get("duration", "")
                )
                duration = self._parse_iso8601_duration(duration_str)

                all_videos.append(
                    {
                        "id": item["id"],
                        "title": item.get("snippet", {}).get("title", ""),
                        "duration": duration,
                        "published_at": item.get("snippet", {}).get(
                            "publishedAt", ""
                        ),
                    }
                )

        return all_videos

    def get_video_by_id(self, video_id: str) -> Optional[dict]:
        """Get details for a single video

        Args:
            video_id: YouTube video ID

        Returns:
            Video details dict if found, None otherwise
        """
        videos = self.get_videos_details([video_id])
        return videos[0] if videos else None

    def close(self):
        """Close the HTTP client"""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
