"""Kick.com internal v2 API client

Uses curl_cffi with TLS fingerprint impersonation to bypass Cloudflare
anti-bot protection. Accesses the internal v2 API at kick.com/api/v2/
which is public but requires a browser-like TLS fingerprint.
No authentication is required.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class KickClient:
    """Client for Kick.com internal v2 API (Cloudflare bypass via curl_cffi)"""

    BASE_URL = "https://kick.com/api/v2"

    def __init__(self):
        # Lazy import so monitor.py can be imported even if curl_cffi is
        # unavailable (only breaks when actually constructing KickClient)
        try:
            import curl_cffi.requests
        except ImportError:
            raise ImportError(
                "curl_cffi is required for Kick API access. "
                "Install with: pip install curl-cffi"
            )

        self._session = curl_cffi.requests.Session()
        self._session.impersonate = "chrome131"
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        })

    def get_channel_by_slug(self, slug: str) -> Optional[dict]:
        """Look up a Kick channel by its slug (URL name).

        GET /api/v2/channels/{slug}

        Returns dict with channel info or None if not found.
        """
        response = self._session.get(f"{self.BASE_URL}/channels/{slug}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def get_vods_by_slug(self, slug: str) -> list[dict]:
        """Get recent VODs for a Kick channel.

        GET /api/v2/channels/{slug}/videos

        Returns list of video dicts with keys like: id (UUID), title,
        duration (seconds), created_at (ISO 8601).
        """
        response = self._session.get(
            f"{self.BASE_URL}/channels/{slug}/videos"
        )
        response.raise_for_status()
        data = response.json()

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("videos", "data", "items"):
                if key in data:
                    return data[key]
            return []
        return []

    def get_video_by_uuid(self, uuid: str) -> Optional[dict]:
        """Get a single Kick VOD by UUID.

        GET /api/v2/videos/{uuid}

        Returns video dict or None if not found.
        """
        response = self._session.get(f"{self.BASE_URL}/videos/{uuid}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def close(self):
        """Close the HTTP session"""
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
