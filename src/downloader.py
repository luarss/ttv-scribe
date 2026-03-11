"""Downloader for Twitch VODs using yt-dlp"""
import logging
import os
import yt_dlp

from .config import get_settings
from .state import get_pending_vods, get_state_manager, VodStatus

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
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
            }],
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }

        logger.info(f"Downloading VOD {vod_id}: {title}")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([twitch_url])

        # Find the downloaded file
        mp3_path = os.path.join(self.output_dir, f"{vod_id}.mp3")

        if not os.path.exists(mp3_path):
            raise FileNotFoundError(f"Expected output file not found: {mp3_path}")

        logger.info(f"Downloaded VOD {vod_id} to {mp3_path}")
        return mp3_path

    def cleanup_audio(self, filepath: str):
        """Remove downloaded audio file"""
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Cleaned up audio file: {filepath}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {filepath}: {e}")


def process_pending_vods(max_vods: int | None = None) -> int:
    """Process pending VODs

    Args:
        max_vods: Maximum number of VODs to process (None = no limit)

    Returns:
        Number of VODs processed
    """
    processed = 0
    downloader = Downloader()
    manager = get_state_manager()

    # Get all pending VODs
    pending_vods = get_pending_vods()

    # Limit to max_vods if specified
    if max_vods is not None:
        pending_vods = pending_vods[:max_vods]

    for vod_data in pending_vods:
        vod_id = vod_data["vod_id"]
        try:
            # Update status to DOWNLOADING
            manager.update_vod(vod_id, status=VodStatus.DOWNLOADING.value)

            # Download audio
            downloader.download_vod_audio(vod_data)

            processed += 1
            logger.info(f"Downloaded VOD {vod_id}")
        except Exception as e:
            logger.error(f"Failed to download VOD {vod_id}: {e}")
            manager.update_vod(vod_id, status=VodStatus.FAILED.value)

    return processed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = process_pending_vods()
    logger.info(f"Processed {count} VODs")