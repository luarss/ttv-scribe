"""Monkey-patch yt-dlp Bilibili extractor with challenge (HTTP 412) solver.

Bilibili sends HTTP 412 with a JWT token to non-China IPs. The client must
solve a SHA256 proof-of-work challenge, submit the solution, and retry with
the returned token as a cookie.

Source: https://security.bilibili.com/static/js/412.js
Based on: https://github.com/yt-dlp/yt-dlp/pull/16578
"""

import hashlib
import logging
import time

from yt_dlp.extractor.bilibili import BilibiliBaseIE
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import (
    ExtractorError,
    jwt_decode_hs256,
    join_nonempty,
    urlencode_postdata,
)

logger = logging.getLogger(__name__)

_CHALLENGE_COOKIE = "X-BILI-SEC-TOKEN"

# Cache the solved token across extractor instances (class-level)
_bili_auth_cache: dict[str, str] = {}  # bvid -> token


def _bili_challenge_result(data, limit=5_000_000):
    """Solve Bilibili's SHA256 proof-of-work challenge."""
    if int(data.get("type")) != 1:
        return False
    final_hash = data.get("r")
    q = data.get("q")
    for i in map(str, range(limit)):
        if hashlib.sha256((q + i).encode()).hexdigest() == final_hash:
            logger.info(f"Bilibili challenge solved: result={i}")
            return i
    return None


def _is_jwt_expired(token):
    """Check if a JWT token expires within 5 minutes."""
    return jwt_decode_hs256(token)["exp"] - time.time() < 300


def _get_cached_token():
    """Get a non-expired cached token if available."""
    for bvid, token in list(_bili_auth_cache.items()):
        cached_token = token.split(",", 1)[-1]
        if not _is_jwt_expired(cached_token):
            return token
        del _bili_auth_cache[bvid]
    return None


def _patched_download_webpage_handle(self, url_or_request, video_id, note=None, headers=None, data=None, **kwargs):
    """Override _download_webpage_handle to solve Bilibili 412 challenges."""
    try:
        return _original_download_webpage_handle(
            self, url_or_request, video_id, note, data=data, headers=headers, **kwargs
        )
    except ExtractorError as e:
        if not (isinstance(e.cause, HTTPError) and e.cause.status == 412):
            raise

        # Try fetching the challenge token from response cookies
        bili_cookie = self._get_cookies("https://www.bilibili.com").get(_CHALLENGE_COOKIE)
        if not bili_cookie:
            raise

        bili_token = bili_cookie.value.split(",", 1)[-1]
        logger.info(
            "Received Bilibili challenge (%s), solving proof-of-work...",
            video_id or "unknown",
        )

        # Check if we have a cached token
        if cached_token := _get_cached_token():
            logger.info("Using cached Bilibili auth token")
            self._set_cookie("www.bilibili.com", _CHALLENGE_COOKIE, cached_token)
            return _original_download_webpage_handle(
                self, url_or_request, video_id, note, data=data, headers=headers, **kwargs
            )

        # Solve the challenge
        token_data = jwt_decode_hs256(bili_token)
        challenge_result = _bili_challenge_result(token_data)
        if not challenge_result:
            logger.warning(
                "Failed to solve Bilibili challenge for %s "
                "(proof-of-work exceeded limit)",
                video_id,
            )
            raise

        challenge_response = self._download_json(
            "https://security.bilibili.com/th/captcha/cc/check",
            None,
            "Submitting challenge solution",
            errnote="Unable to submit challenge solution",
            data=urlencode_postdata({
                "token": bili_token,
                "result": challenge_result,
            }),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        new_token = challenge_response.get("message")
        if int(challenge_response.get("code")) != 0:
            raise ExtractorError(
                f"Failed to solve Bilibili challenge: API returned {new_token}"
            )

        # Cache and set the new token
        logger.info("Bilibili challenge solved, retrying...")
        self._set_cookie("www.bilibili.com", _CHALLENGE_COOKIE, new_token)
        _bili_auth_cache[video_id or "default"] = new_token

        return _original_download_webpage_handle(
            self, url_or_request, video_id, note, data=data, headers=headers, **kwargs
        )


_original_download_webpage_handle = None
_patch_applied = False


def apply_patch():
    """Apply the Bilibili challenge solver patch. Idempotent."""
    global _original_download_webpage_handle, _patch_applied
    if _patch_applied:
        return

    _original_download_webpage_handle = BilibiliBaseIE._download_webpage_handle
    BilibiliBaseIE._download_webpage_handle = _patched_download_webpage_handle
    _patch_applied = True
    logger.info("Bilibili challenge solver patch applied")
