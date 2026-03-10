"""Monitor for checking new VODs from tracked streamers"""
import logging
from datetime import datetime

from .database import get_db_session
from .models import Streamer, Vod, VodStatus
from .twitch.client import TwitchClient

logger = logging.getLogger(__name__)


def check_for_new_vods() -> int:
    """Check for new VODs from all tracked streamers

    Returns:
        Number of new VODs found
    """
    new_vod_count = 0

    with get_db_session() as session:
        # Get all tracked streamers
        streamers = session.query(Streamer).all()

        for streamer in streamers:
            try:
                new_count = _check_streamer_vods(session, streamer)
                new_vod_count += new_count
            except Exception as e:
                logger.error(f"Error checking VODs for {streamer.username}: {e}")

    return new_vod_count


def _check_streamer_vods(session, streamer: Streamer) -> int:
    """Check for new VODs for a specific streamer

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

        # Parse duration (could be "HH:MM:SS" or just seconds)
        duration = vod_data.get("duration")
        if duration:
            # Try to parse "HH:MM:SS" format
            try:
                parts = duration.split(":")
                if len(parts) == 3:
                    duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                elif len(parts) == 2:
                    duration = int(parts[0]) * 60 + int(parts[1])
                else:
                    duration = int(parts[0])
            except (ValueError, IndexError):
                duration = None

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