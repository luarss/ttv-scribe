"""Bilibili API client

Uses WBI-signed requests with anti-bot fingerprinting parameters
for user video listing, and direct API calls for individual video lookups.
"""

import base64
import hashlib
import logging
import random
import string
import time
from typing import Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# Fixed mixing table for WBI key derivation (from Bilibili frontend JS)
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]


class BilibiliClient:
    """Client for Bilibili API interaction (no auth required for public content)"""

    BASE_URL = "https://api.bilibili.com"

    def __init__(self):
        self._client = httpx.Client(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Referer": "https://www.bilibili.com",
            },
        )
        self._mixin_key: Optional[str] = None
        self._mixin_key_ts: float = 0

        # Get session cookies by visiting bilibili.com
        self._init_session()

    def _init_session(self):
        """Visit bilibili.com to get session cookies (buvid3, b_nut)"""
        try:
            self._client.get("https://www.bilibili.com")
        except Exception as e:
            logger.warning(f"Failed to initialize Bilibili session: {e}")

    def _get_wbi_key(self) -> str:
        """Fetch and cache WBI signing key"""
        if self._mixin_key and (time.time() - self._mixin_key_ts) < 300:
            return self._mixin_key

        response = self._client.get(f"{self.BASE_URL}/x/web-interface/nav")
        response.raise_for_status()
        data = response.json()

        wbi_img = data.get("data", {}).get("wbi_img", {})
        img_key = wbi_img.get("img_url", "").rsplit("/", 1)[1].split(".")[0]
        sub_key = wbi_img.get("sub_url", "").rsplit("/", 1)[1].split(".")[0]
        lookup = img_key + sub_key

        self._mixin_key = "".join(lookup[i] for i in MIXIN_KEY_ENC_TAB)[:32]
        self._mixin_key_ts = time.time()
        return self._mixin_key

    def _sign_wbi(self, params: dict) -> dict:
        """Sign params with WBI signature, matching yt-dlp's implementation"""
        wbi_key = self._get_wbi_key()

        params["wts"] = round(time.time())
        # Filter special chars from values, then sort by key
        params = {
            k: "".join(c for c in str(v) if c not in "!'()*")
            for k, v in sorted(params.items())
        }
        query = urlencode(params)
        params["w_rid"] = hashlib.md5(f"{query}{wbi_key}".encode()).hexdigest()
        return params

    def _generate_fingerprint_params(self) -> dict:
        """Generate anti-bot fingerprinting parameters"""
        return {
            "dm_img_list": "[]",
            "dm_img_str": base64.b64encode(
                "".join(random.choices(string.printable, k=random.randint(16, 64))).encode()
            )[:-2].decode(),
            "dm_cover_img_str": base64.b64encode(
                "".join(random.choices(string.printable, k=random.randint(32, 128))).encode()
            )[:-2].decode(),
            "dm_img_inter": '{"ds":[],"wh":[6093,6631,31],"of":[430,760,380]}',
        }

    def get_user_by_username(self, username: str) -> Optional[dict]:
        """Search for Bilibili user by username

        Note: Search may not return exact match. For reliability,
        users should provide the mid (user ID) directly.
        """
        response = self._client.get(
            f"{self.BASE_URL}/x/web-interface/search/type",
            params={"search_type": "bili_user", "keyword": username},
        )
        response.raise_for_status()
        data = response.json()

        users = data.get("data", {}).get("result", [])
        if users:
            user = users[0]
            return {"id": str(user["mid"]), "name": user["uname"]}
        return None

    def get_videos_by_mid(
        self, mid: str, page: int = 1, page_size: int = 50, retries: int = 2
    ) -> list[dict]:
        """Get videos for a Bilibili user by their mid (user ID)

        Args:
            mid: Bilibili user ID (member ID)
            page: Page number (1-indexed)
            page_size: Number of videos per page (max 50)
            retries: Number of retries on -352 errors

        Returns:
            List of video dicts with keys: bvid, title, duration, created, etc.
        """
        query = {
            "keyword": "",
            "mid": mid,
            "order": "pubdate",
            "order_avoided": "true",
            "platform": "web",
            "pn": page,
            "ps": page_size,
            "tid": 0,
            "web_location": 1550101,
            **self._generate_fingerprint_params(),
        }

        for attempt in range(retries + 1):
            signed = self._sign_wbi(query)
            response = self._client.get(
                f"{self.BASE_URL}/x/space/wbi/arc/search",
                params=signed,
                headers={"Referer": f"https://space.bilibili.com/{mid}/video"},
            )
            response.raise_for_status()
            data = response.json()

            if data.get("code") == -352:
                if attempt < retries:
                    wait = 5 * (attempt + 1)
                    logger.warning(f"WBI -352 error, retrying in {wait}s (attempt {attempt + 1}/{retries})")
                    time.sleep(wait)
                    # Refresh WBI key on retry
                    self._mixin_key = None
                    continue
                logger.error(f"WBI signing rejected after {retries} retries")
                return []

            if data.get("code") != 0:
                logger.error(f"Bilibili API error {data.get('code')}: {data.get('message')}")
                return []

            videos = data.get("data", {}).get("list", {}).get("vlist", [])
            return videos

        return []

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
