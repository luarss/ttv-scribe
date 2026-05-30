"""Kuaishou GraphQL API client

Python port of the Kuaishou module from ikenxuan/amagi.
Uses Kuaishou's internal GraphQL endpoint to fetch video metadata,
stream URLs, and user profile data.
"""

import json
import logging
import random
import re
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://www.kuaishou.com/graphql"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.kuaishou.com",
    "Content-Type": "application/json",
}

VISION_VIDEO_DETAIL_QUERY = """
query visionVideoDetail(
    $photoId: String, $type: String, $page: String, $webPageArea: String
) {
    visionVideoDetail(
        photoId: $photoId, type: $type, page: $page, webPageArea: $webPageArea
    ) {
        status
        type
        author { id name following headerUrl __typename }
        photo {
            id duration caption likeCount realLikeCount
            coverUrl photoUrl timestamp viewCount videoRatio stereoType
            manifest {
                mediaType businessType version
                adaptationSet {
                    id duration
                    representation {
                        id defaultSelect backupUrl codecs url
                        height width avgBitrate maxBitrate m3u8Slice
                        qualityType qualityLabel frameRate
                        featureP2sp hidden disableAdaptive
                        __typename
                    }
                    __typename
                }
                __typename
            }
            __typename
        }
        tags { type name __typename }
        __typename
    }
}
"""

VISION_PROFILE_QUERY = """
query visionProfile($userId: String) {
    visionProfile(userId: $userId) {
        result
        userProfile {
            ownerCount { fan photo follow __typename }
            profile { gender user_name user_id headurl __typename }
            isFollowing
            __typename
        }
        __typename
    }
}
"""

VISION_PROFILE_PHOTO_LIST_QUERY = """
query visionProfilePhotoList(
    $userId: String, $pcursor: String, $page: String, $webPageArea: String
) {
    visionProfilePhotoList(
        userId: $userId, pcursor: $pcursor,
        page: $page, webPageArea: $webPageArea
    ) {
        result
        pcursor
        feeds {
            photo {
                id duration caption likeCount realLikeCount
                coverUrl photoUrl timestamp viewCount videoRatio stereoType
                __typename
            }
            __typename
        }
        __typename
    }
}
"""

VISION_SEARCH_PHOTO_QUERY = """
query visionSearchPhoto(
    $keyword: String, $pcursor: String, $searchSessionId: String,
    $page: String, $webPageArea: String
) {
    visionSearchPhoto(
        keyword: $keyword, pcursor: $pcursor,
        searchSessionId: $searchSessionId,
        page: $page, webPageArea: $webPageArea
    ) {
        result
        pcursor
        feeds {
            photo {
                id duration caption likeCount realLikeCount
                coverUrl photoUrl timestamp viewCount videoRatio stereoType
                __typename
            }
            author { id name following headerUrl __typename }
            __typename
        }
        __typename
    }
}
"""


class KuaishouClient:
    """Client for Kuaishou GraphQL API interaction."""

    def __init__(self):
        self._client = httpx.Client(timeout=30.0, headers=DEFAULT_HEADERS)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _graphql(self, operation_name: str, variables: dict, query: str) -> dict:
        """Execute a GraphQL query and return the response data.

        Args:
            operation_name: The GraphQL operation name.
            variables: Variables dict for the query.
            query: The GraphQL query string.

        Returns:
            The response JSON data dict.

        Raises:
            httpx.HTTPStatusError: On HTTP errors.
            ValueError: On GraphQL errors or empty responses.
        """
        payload = {
            "operationName": operation_name,
            "variables": variables,
            "query": query,
        }
        body = json.dumps(payload, separators=(",", ":"))

        response = self._client.post(GRAPHQL_URL, content=body)
        response.raise_for_status()
        data = response.json()

        errors = data.get("errors")
        if errors:
            msg = errors[0].get("message", str(errors)) if errors else "Unknown error"
            raise ValueError(f"GraphQL error for {operation_name}: {msg}")

        return data

    # ---- Public API methods ----

    def get_work_info(self, photo_id: str) -> Optional[dict]:
        """Get video detail including stream URLs via visionVideoDetail.

        Args:
            photo_id: Kuaishou photo/video ID.

        Returns:
            Normalized dict with keys: photo_id, title, duration, author_id,
            author_name, cover_url, stream_urls, like_count, view_count,
            tags, timestamp_ms. Returns None if the video isn't found.
        """
        variables = {
            "photoId": photo_id,
            "type": "detail",
            "page": "detail",
            "webPageArea": "videoDetail",
        }
        try:
            data = self._graphql(
                "visionVideoDetail", variables, VISION_VIDEO_DETAIL_QUERY
            )
        except Exception:
            logger.debug(f"visionVideoDetail failed for {photo_id}", exc_info=True)
            return None

        detail = data.get("data", {}).get("visionVideoDetail")
        if not detail:
            return None

        author = detail.get("author") or {}
        photo = detail.get("photo") or {}
        manifest = photo.get("manifest") or {}

        stream_urls = []
        for adapt_set in manifest.get("adaptationSet", []):
            for rep in adapt_set.get("representation", []):
                url = rep.get("url") or rep.get("backupUrl")
                if url:
                    stream_urls.append({
                        "url": url,
                        "quality": rep.get("qualityLabel") or rep.get("qualityType", ""),
                        "height": rep.get("height"),
                        "width": rep.get("width"),
                        "avg_bitrate": rep.get("avgBitrate"),
                        "m3u8": bool(rep.get("m3u8Slice")),
                    })

        tags = [t.get("name", "") for t in (detail.get("tags") or []) if t.get("name")]

        return {
            "photo_id": photo.get("id", photo_id),
            "title": photo.get("caption"),
            "duration": photo.get("duration"),
            "author_id": author.get("id"),
            "author_name": author.get("name"),
            "cover_url": photo.get("coverUrl"),
            "stream_urls": stream_urls,
            "like_count": photo.get("realLikeCount") or photo.get("likeCount"),
            "view_count": photo.get("viewCount"),
            "tags": tags,
            "timestamp_ms": photo.get("timestamp"),
        }

    def get_user_profile(self, user_id: str) -> Optional[dict]:
        """Get Kuaishou user profile via visionProfile.

        Args:
            user_id: Kuaishou user ID.

        Returns:
            Normalized dict with user_id, user_name, headurl, fan_count,
            photo_count, follow_count, or None if not found.
        """
        try:
            data = self._graphql("visionProfile", {"userId": user_id}, VISION_PROFILE_QUERY)
        except Exception:
            logger.debug(f"visionProfile failed for {user_id}", exc_info=True)
            return None

        profile = data.get("data", {}).get("visionProfile", {})
        user_profile = profile.get("userProfile") or {}

        owner_count = user_profile.get("ownerCount") or {}
        prof = user_profile.get("profile") or {}

        return {
            "user_id": prof.get("user_id", user_id),
            "user_name": prof.get("user_name"),
            "headurl": prof.get("headurl"),
            "fan_count": owner_count.get("fan"),
            "photo_count": owner_count.get("photo"),
            "follow_count": owner_count.get("follow"),
        }

    def get_user_videos(
        self, user_id: str, pcursor: str = ""
    ) -> dict:
        """Get a page of a user's videos via visionProfilePhotoList.

        Args:
            user_id: Kuaishou user ID.
            pcursor: Pagination cursor (empty string for first page).

        Returns:
            Dict with keys: feeds (list of normalized video dicts),
            pcursor (next cursor, or "no_more" when done).
        """
        variables = {
            "userId": user_id,
            "pcursor": pcursor,
            "page": "profile",
            "webPageArea": "profile",
        }
        data = self._graphql(
            "visionProfilePhotoList", variables, VISION_PROFILE_PHOTO_LIST_QUERY
        )
        result = data.get("data", {}).get("visionProfilePhotoList") or {}

        feeds = []
        for item in result.get("feeds", []):
            photo = item.get("photo") or {}
            feeds.append({
                "photo_id": photo.get("id"),
                "caption": photo.get("caption"),
                "duration": photo.get("duration"),
                "cover_url": photo.get("coverUrl"),
                "like_count": photo.get("realLikeCount") or photo.get("likeCount"),
                "view_count": photo.get("viewCount"),
                "timestamp_ms": photo.get("timestamp"),
            })

        return {
            "feeds": feeds,
            "pcursor": result.get("pcursor", "no_more"),
        }

    def get_videos_by_user_id(self, user_id: str) -> list[dict]:
        """Get all videos for a user, handling cursor-based pagination.

        Args:
            user_id: Kuaishou user ID.

        Returns:
            Flat list of all video dicts.
        """
        all_feeds = []
        pcursor = ""

        while True:
            result = self.get_user_videos(user_id, pcursor)
            feeds = result.get("feeds", [])
            all_feeds.extend(feeds)

            pcursor = result.get("pcursor", "no_more")
            if pcursor == "no_more" or not feeds:
                break

            time.sleep(random.uniform(0.5, 1.5))

        return all_feeds

    def search_videos(self, keyword: str, pcursor: str = "") -> dict:
        """Search Kuaishou videos via visionSearchPhoto.

        Args:
            keyword: Search keyword (e.g., username).
            pcursor: Pagination cursor.

        Returns:
            Dict with feeds (list of dicts) and pcursor.
        """
        variables = {
            "keyword": keyword,
            "pcursor": pcursor,
            "searchSessionId": "",
            "page": "search",
            "webPageArea": "search",
        }
        data = self._graphql(
            "visionSearchPhoto", variables, VISION_SEARCH_PHOTO_QUERY
        )
        result = data.get("data", {}).get("visionSearchPhoto") or {}

        feeds = []
        for item in result.get("feeds", []):
            photo = item.get("photo") or {}
            author = item.get("author") or {}
            feeds.append({
                "photo_id": photo.get("id"),
                "caption": photo.get("caption"),
                "duration": photo.get("duration"),
                "cover_url": photo.get("coverUrl"),
                "like_count": photo.get("realLikeCount") or photo.get("likeCount"),
                "view_count": photo.get("viewCount"),
                "timestamp_ms": photo.get("timestamp"),
                "author_id": author.get("id"),
                "author_name": author.get("name"),
            })

        return {
            "feeds": feeds,
            "pcursor": result.get("pcursor", "no_more"),
        }

    def discover_user_id(self, username: str) -> Optional[str]:
        """Try to find a user's Kuaishou ID from their username.

        First tries search, then falls back to profile page scraping.

        Args:
            username: The Kuaishou username to look up.

        Returns:
            Kuaishou user ID string, or None if not found.
        """
        # Strategy 1: Search for the username
        try:
            result = self.search_videos(username)
            for item in result.get("feeds", []):
                if item.get("author_name") == username:
                    return item.get("author_id")
        except Exception as e:
            logger.debug(f"Search-based user discovery failed for {username}: {e}")

        # Strategy 2: Scrape profile page
        try:
            profile_url = f"https://www.kuaishou.com/profile/{username}"
            resp = self._client.get(profile_url, follow_redirects=True)
            resp.raise_for_status()
            for pattern in (r'"userId"\s*:\s*"([^"]+)"', r'"principalId"\s*:\s*"([^"]+)"'):
                match = re.search(pattern, resp.text)
                if match:
                    return match.group(1)
        except Exception as e:
            logger.debug(f"Profile scrape failed for {username}: {e}")

        return None
