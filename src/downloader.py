"""Downloader for Twitch VODs using yt-dlp"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import yt_dlp

from .config import get_settings
from .state import StateManager, VodStatus

logger = logging.getLogger(__name__)


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

        twitch_url = f"https://www.twitch.tv/videos/{vod_id}"

        # Create temp file for output
        output_template = os.path.join(self.output_dir, f"{vod_id}.%(ext)s")

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
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

        logger.info(f"Downloading VOD {vod_id}: {title}")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([twitch_url])

        # Find the downloaded file
        opus_path = os.path.join(self.output_dir, f"{vod_id}.opus")

        if not os.path.exists(opus_path):
            raise FileNotFoundError(f"Expected output file not found: {opus_path}")

        logger.info(f"Downloaded VOD {vod_id} to {opus_path}")
        return opus_path

    def cleanup_audio(self, filepath: str):
        """Remove downloaded audio file"""
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Cleaned up audio file: {filepath}")
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

            logger.info(f"Downloaded VOD {vod_id}")
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
