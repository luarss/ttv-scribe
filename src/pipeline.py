"""Processing pipeline for TTV-Scribe"""
import logging

from .monitor import check_for_new_vods, add_streamers_to_track
from .monthly_tracker import get_usage_info, update_github_minutes
from .downloader import process_pending_vods
from .transcriber_local import process_downloaded_vods

logger = logging.getLogger(__name__)


def run_pipeline(max_duration_minutes: int | None = None, max_vods: int | None = None):
    """Run the full processing pipeline

    Args:
        max_duration_minutes: Only process VODs shorter than this duration (None = no limit)
        max_vods: Maximum number of VODs to process from queue (None = no limit)
    """
    logger.info("Starting TTV-Scribe pipeline")

    # Update GitHub Actions minutes from API
    update_github_minutes()

    # Log monthly usage
    usage = get_usage_info()
    logger.info(
        f"Monthly usage: {usage['minutes_used']:.1f}/{usage['limit']} minutes "
        f"({usage['remaining']:.1f} remaining for {usage['year']}-{usage['month']:02d})"
    )
    logger.info(f"GitHub Actions minutes used: {usage.get('github_minutes_used', 0):.1f}")

    # Step 1: Check for new VODs
    try:
        new_vods = check_for_new_vods(max_duration_minutes=max_duration_minutes)
        logger.info(f"Found {new_vods} new VODs")
    except Exception as e:
        logger.error(f"Error in monitor step: {e}")
        new_vods = 0

    # Step 2: Download pending VODs
    try:
        downloaded = process_pending_vods(max_vods=max_vods)
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
