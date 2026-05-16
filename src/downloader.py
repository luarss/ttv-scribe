"""Downloader for Twitch VODs using yt-dlp"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import yt_dlp

from .bilibili_patch import apply_patch
from .config import get_settings
from .state import StateManager, VodStatus

# Apply the Bilibili HTTP 412 challenge solver patch at import time
apply_patch()

logger = logging.getLogger(__name__)


def _bilibili_impersonation_target():
    """Return an ImpersonateTarget if curl_cffi is available, else None."""
    try:
        import curl_cffi  # noqa: F401
        from yt_dlp.networking.impersonate import ImpersonateTarget

        version = tuple(int(p) for p in curl_cffi.__version__.split(".")[:3])
        if version == (0, 5, 10) or (0, 10) <= version < (0, 15):
            return ImpersonateTarget.from_str("chrome-131")
    except (ImportError, ValueError):
        pass
    return None


class Downloader:
    """Downloader for Twitch VOD audio"""

    def __init__(self):
        self.settings = get_settings()
        self.output_dir = self.settings.audio_output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def download_vod_audio(self, vod_data: dict) -> str:
        """Download audio from a VOD

        Args:
            vod_data: The VOD data dictionary

        Returns:
            Path to the downloaded audio file

        Raises:
            Exception: If download fails
        """
        vod_id = vod_data["vod_id"]
        title = vod_data.get("title", "Unknown")
        platform = vod_data.get("platform", "twitch")

        # Construct URL based on platform
        if platform == "bilibili":
            video_url = f"https://www.bilibili.com/video/{vod_id}"
        elif platform == "youtube":
            video_url = f"https://www.youtube.com/watch?v={vod_id}"
        else:
            video_url = f"https://www.twitch.tv/videos/{vod_id}"

        # Create temp file for output
        output_template = os.path.join(self.output_dir, f"{vod_id}.%(ext)s")

        ydl_opts = {
            # Limit source audio to 128k to avoid huge downloads before conversion
            # Twitch typically offers audio-only streams at various qualities
            "format": "bestaudio[abr<=128k]/bestaudio",
            "outtmpl": output_template,
            # Speed up HLS fragment downloads
            "concurrent_fragment_downloads": 8,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "opus",
                }
            ],
            "postprocessor_args": {
                "FFmpegExtractAudio": ["-b:a", "24k", "-ar", "16000", "-ac", "1"]
            },
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }

        # Bilibili anti-bot measures (challenge solver patches HTTP 412 at extractor level;
        # these options reduce the chance of being challenged in the first place)
        if platform == "bilibili":
            ydl_opts["sleep_interval_requests"] = 2
            ydl_opts["http_headers"] = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Referer": "https://www.bilibili.com",
            }
            if target := _bilibili_impersonation_target():
                ydl_opts["impersonate"] = target

        # Use aria2c if available for faster downloads
        if os.path.exists("/usr/bin/aria2c") or os.path.exists("/usr/local/bin/aria2c"):
            ydl_opts["external_downloader"] = "aria2c"
            ydl_opts["external_downloader_args"] = ["-x", "8", "-k", "1M", "-s", "8"]

        duration_min = vod_data.get("duration", 0) / 60 if vod_data.get("duration") else 0
        logger.info(f"Downloading VOD {vod_id} ({title}, {duration_min:.0f}min)")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        # Find the downloaded file
        opus_path = os.path.join(self.output_dir, f"{vod_id}.opus")

        if not os.path.exists(opus_path):
            raise FileNotFoundError(f"Expected output file not found: {opus_path}")

        logger.debug(f"Downloaded VOD {vod_id} to {opus_path}")
        return opus_path

    def cleanup_audio(self, filepath: str):
        """Remove downloaded audio file"""
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.debug(f"Cleaned up audio file: {filepath}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {filepath}: {e}")


def process_pending_vods(max_vods: int | None = None, max_workers: int = 3) -> int:
    """Process pending VODs in parallel

    Args:
        max_vods: Maximum number of VODs to process (None = no limit)
        max_workers: Maximum number of concurrent downloads

    Returns:
        Number of VODs processed
    """
    from .state import get_pending_vods

    processed = 0
    downloader = Downloader()

    # Get all pending VODs and sort by duration (shortest first)
    pending_vods = get_pending_vods()

    # Sort by duration, shortest first; VODs without duration go to the end
    pending_vods.sort(
        key=lambda v: v.get("duration") if v.get("duration") else float("inf")
    )

    # Limit to max_vods if specified
    if max_vods is not None:
        pending_vods = pending_vods[:max_vods]

    if not pending_vods:
        return 0

    # Create a thread-safe wrapper for downloading a single VOD
    def download_single_vod(vod_data: dict) -> tuple[bool, str]:
        """Download a single VOD with its own state manager

        Returns:
            Tuple of (success, vod_id)
        """
        # Each thread gets its own StateManager to avoid race conditions
        manager = StateManager()
        vod_id = vod_data["vod_id"]

        try:
            # Update status to DOWNLOADING
            manager.update_vod(vod_id, status=VodStatus.DOWNLOADING.value)

            # Download audio
            downloader.download_vod_audio(vod_data)

            logger.debug(f"Downloaded VOD {vod_id}")
            return (True, vod_id)
        except Exception as e:
            logger.error(f"Failed to download VOD {vod_id}: {e}")
            manager.update_vod(vod_id, status=VodStatus.FAILED.value)
            return (False, vod_id)

    # Process VODs in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all download tasks
        future_to_vod = {
            executor.submit(download_single_vod, vod_data): vod_data
            for vod_data in pending_vods
        }

        # Collect results as they complete
        for future in as_completed(future_to_vod):
            success, vod_id = future.result()
            if success:
                processed += 1

    return processed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = process_pending_vods()
    logger.info(f"Processed {count} VODs")
