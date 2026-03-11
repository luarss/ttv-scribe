"""Monitor for checking new VODs from tracked streamers"""
import logging
from datetime import datetime

from .state import (
    get_streamers,
    add_streamer,
    update_streamer,
    get_state_manager,
    VodRecord,
    VodStatus,
)
from .twitch.client import TwitchClient

logger = logging.getLogger(__name__)


def check_for_new_vods(max_duration_minutes: int | None = None) -> int:
    """Check for new VODs from all tracked streamers

    Args:
        max_duration_minutes: Only include VODs shorter than this duration (None = no limit)

    Returns:
        Number of new VODs found
    """
    new_vod_count = 0

    # Get all tracked streamers
    streamers = get_streamers()

    if not streamers:
        logger.warning("No streamers to monitor. Add streamers first.")

    for streamer_data in streamers:
        try:
            new_count = _check_streamer_vods(
                streamer_data["username"],
                streamer_data.get("twitch_id"),
                max_duration_minutes,
            )
            new_vod_count += new_count
        except Exception as e:
            logger.error(f"Error checking VODs for {streamer_data['username']}: {e}")

    return new_vod_count


def _check_streamer_vods(
    username: str,
    twitch_id: str | None,
    max_duration_minutes: int | None = None,
) -> int:
    """Check for new VODs for a specific streamer

    Args:
        username: The streamer's username
        twitch_id: Optional Twitch user ID
        max_duration_minutes: Only include VODs shorter than this duration (None = no limit)

    Returns:
        Number of new VODs added
    """
    with TwitchClient() as twitch:
        # Get Twitch user info if we don't have it
        if not twitch_id:
            user = twitch.get_user_by_username(username)
            if not user:
                logger.warning(f"Streamer {username} not found on Twitch")
                return 0
            twitch_id = user["id"]
            # Save the twitch_id for future use
            update_streamer(username, twitch_id=twitch_id)

        # Get VODs
        vods_data = twitch.get_vods_by_user(twitch_id)

    # Get state manager to check for existing VODs
    manager = get_state_manager()
    new_count = 0

    for vod_data in vods_data:
        vod_id = vod_data["id"]

        # Check if we already have this VOD
        existing = manager.get_vod(vod_id)
        if existing:
            continue

        # Parse recorded_at
        recorded_at = vod_data.get("created_at")
        if recorded_at:
            # Convert to ISO format
            recorded_at = recorded_at.replace("Z", "+00:00")

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

        # Filter by max duration (skip if max_duration_minutes is None)
        if max_duration_minutes is not None and duration is not None and duration > max_duration_minutes * 60:
            logger.debug(f"Skipping VOD {vod_id} - too long ({duration}s)")
            continue

        if duration is not None:
            logger.debug(f"VOD {vod_id} duration: {duration}s ({duration/60:.1f} min)")

        # Add new VOD to state
        vod = VodRecord(
            vod_id=vod_id,
            streamer=username,
            title=vod_data.get("title"),
            duration=duration,
            recorded_at=recorded_at,
            status=VodStatus.PENDING,
        )
        manager.add_vod(vod)
        new_count += 1
        logger.info(f"Added new VOD {vod_id} for {username}: {vod_data.get('title')}")

    return new_count


def add_streamers_to_track(usernames: list[str]) -> int:
    """Add streamers to track

    Args:
        usernames: List of streamer usernames to add

    Returns:
        Number of streamers added
    """
    added = 0
    for username in usernames:
        existing = get_streamer(username)
        if not existing:
            add_streamer(username)
            added += 1
            logger.info(f"Added {username} to tracking")
    return added


def get_streamer(username: str) -> dict | None:
    """Get a streamer by username

    Args:
        username: The streamer username

    Returns:
        Streamer data as dict if found, None otherwise
    """
    from .state import get_state_manager
    manager = get_state_manager()
    streamer = manager.get_streamer(username)
    return streamer.to_dict() if streamer else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = check_for_new_vods()
    logger.info(f"Found {count} new VODs")