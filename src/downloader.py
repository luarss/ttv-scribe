"""Downloader for Twitch VODs using yt-dlp"""
import logging
import os
import tempfile
import yt_dlp

from .config import get_settings
from .database import get_db_session
from .models import Vod, VodStatus

logger = logging.getLogger(__name__)


class Downloader:
    """Downloader for Twitch VOD audio"""

    def __init__(self):
        self.settings = get_settings()
        self.output_dir = self.settings.audio_output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def download_vod_audio(self, vod: Vod) -> str:
        """Download audio from a VOD

        Args:
            vod: The Vod object to download

        Returns:
            Path to the downloaded audio file

        Raises:
            Exception: If download fails
        """
        # Update status
        vod.status = VodStatus.DOWNLOADING

        twitch_url = f"https://www.twitch.tv/videos/{vod.vod_id}"

        # Create temp file for output
        output_template = os.path.join(self.output_dir, f"{vod.vod_id}.%(ext)s")

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

        logger.info(f"Downloading VOD {vod.vod_id}: {vod.title}")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([twitch_url])

        # Find the downloaded file
        mp3_path = os.path.join(self.output_dir, f"{vod.vod_id}.mp3")

        if not os.path.exists(mp3_path):
            raise FileNotFoundError(f"Expected output file not found: {mp3_path}")

        logger.info(f"Downloaded VOD {vod.vod_id} to {mp3_path}")
        return mp3_path

    def cleanup_audio(self, filepath: str):
        """Remove downloaded audio file"""
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Cleaned up audio file: {filepath}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {filepath}: {e}")


def process_pending_vods() -> int:
    """Process all pending VODs

    Returns:
        Number of VODs processed
    """
    processed = 0
    downloader = Downloader()

    with get_db_session() as session:
        pending_vods = session.query(Vod).filter(
            Vod.status == VodStatus.PENDING
        ).all()

        for vod in pending_vods:
            try:
                downloader.download_vod_audio(vod)
                # In the full pipeline, this would continue to transcription
                # For now, just mark as downloaded
                processed += 1
            except Exception as e:
                logger.error(f"Failed to download VOD {vod.vod_id}: {e}")
                vod.status = VodStatus.FAILED

    return processed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = process_pending_vods()
    logger.info(f"Processed {count} VODs")