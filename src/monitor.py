"""Monitor for checking new VODs from tracked streamers"""
import logging
from datetime import datetime

from .database import get_db_session
from .models import Streamer, Vod, VodStatus
from .twitch.client import TwitchClient

logger = logging.getLogger(__name__)


def check_for_new_vods(max_duration_minutes: int | None = None) -> int:
    """Check for new VODs from all tracked streamers

    Args:
        max_duration_minutes: If set, only include VODs shorter than this duration

    Returns:
        Number of new VODs found
    """
    new_vod_count = 0

    with get_db_session() as session:
        # Get all tracked streamers
        streamers = session.query(Streamer).all()

        for streamer in streamers:
            try:
                new_count = _check_streamer_vods(session, streamer, max_duration_minutes)
                new_vod_count += new_count
            except Exception as e:
                logger.error(f"Error checking VODs for {streamer.username}: {e}")

    return new_vod_count


def _check_streamer_vods(session, streamer: Streamer, max_duration_minutes: int | None = None) -> int:
    """Check for new VODs for a specific streamer

    Args:
        max_duration_minutes: If set, only include VODs shorter than this duration

    Returns:
        Number of new VODs added
    """
    with TwitchClient() as twitch:
        # Get Twitch user info if we don't have it
        if not streamer.twitch_id:
            user = twitch.get_user_by_username(streamer.username)
            if not user:
                logger.warning(f"Streamer {streamer.username} not found on Twitch")
                return 0
            streamer.twitch_id = user["id"]

        # Get VODs
        vods_data = twitch.get_vods_by_user(streamer.twitch_id)

    new_count = 0
    for vod_data in vods_data:
        vod_id = vod_data["id"]

        # Check if we already have this VOD
        existing = session.query(Vod).filter(Vod.vod_id == vod_id).first()
        if existing:
            continue

        # Add new VOD
        recorded_at = datetime.fromisoformat(
            vod_data["created_at"].replace("Z", "+00:00")
        )

        # Parse duration (Twitch returns "2h3m10s" or "45m30s" format)
        duration = vod_data.get("duration")
        if duration:
            try:
                # Handle Twitch format: "2h3m10s", "45m30s", "30s"
                total_seconds = 0
                current_num = ""
                for char in duration:
                    if char.isdigit():
                        current_num += char
                    elif char == 'h':
                        total_seconds += int(current_num) * 3600
                        current_num = ""
                    elif char == 'm':
                        total_seconds += int(current_num) * 60
                        current_num = ""
                    elif char == 's':
                        total_seconds += int(current_num)
                        current_num = ""
                duration = total_seconds if total_seconds > 0 else None
            except (ValueError, IndexError):
                duration = None

        # Filter by max duration if specified
        if max_duration_minutes is not None and duration is not None:
            if duration > max_duration_minutes * 60:
                logger.debug(f"Skipping VOD {vod_id} - too long ({duration}s)")
                continue

        if duration is not None:
            logger.debug(f"VOD {vod_id} duration: {duration}s ({duration/60:.1f} min)")

        vod = Vod(
            vod_id=vod_id,
            streamer_id=streamer.id,
            title=vod_data.get("title"),
            duration=duration,
            recorded_at=recorded_at,
            status=VodStatus.PENDING,
        )
        session.add(vod)
        new_count += 1
        logger.info(f"Added new VOD {vod_id} for {streamer.username}: {vod_data.get('title')}")

    return new_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = check_for_new_vods()
    logger.info(f"Found {count} new VODs")