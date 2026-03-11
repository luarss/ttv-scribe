"""Processing pipeline for TTV-Scribe"""
import logging
import sys

from .database import init_db
from .monitor import check_for_new_vods
from .downloader import process_pending_vods
from .transcriber import process_downloaded_vods

logger = logging.getLogger(__name__)


def run_pipeline(max_duration_minutes: int | None = None):
    """Run the full processing pipeline

    Args:
        max_duration_minutes: If set, only process VODs shorter than this duration
    """
    logger.info("Starting TTV-Scribe pipeline")

    # Initialize database
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        sys.exit(1)

    # Step 1: Check for new VODs
    try:
        new_vods = check_for_new_vods(max_duration_minutes=max_duration_minutes)
        logger.info(f"Found {new_vods} new VODs")
    except Exception as e:
        logger.error(f"Error in monitor step: {e}")
        new_vods = 0

    # Step 2: Download pending VODs
    try:
        downloaded = process_pending_vods()
        logger.info(f"Downloaded {downloaded} VODs")
    except Exception as e:
        logger.error(f"Error in download step: {e}")
        downloaded = 0

    # Step 3: Transcribe downloaded VODs
    try:
        transcribed = process_downloaded_vods()
        logger.info(f"Transcribed {transcribed} VODs")
    except Exception as e:
        logger.error(f"Error in transcription step: {e}")
        transcribed = 0

    logger.info(f"Pipeline complete: {new_vods} new, {downloaded} downloaded, {transcribed} transcribed")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    run_pipeline()