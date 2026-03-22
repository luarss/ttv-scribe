#!/usr/bin/env python3
"""Re-check failed VODs and reset them to pending if they're available on Twitch."""

import sys
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.state import StateManager, VodStatus
from src.twitch.client import TwitchClient


def main():
    manager = StateManager()
    failed_vods = manager.get_vods_by_status(VodStatus.FAILED)

    if not failed_vods:
        print("No failed VODs to check.")
        return

    print(f"Found {len(failed_vods)} failed VODs. Checking availability...")

    reset_count = 0
    still_failed_count = 0

    with TwitchClient() as twitch:
        for vod in failed_vods:
            vod_id = vod.vod_id
            video = twitch.get_video_by_id(vod_id)

            if video is not None:
                print(f"✓ VOD {vod_id} ({vod.streamer}) is available - resetting to pending")
                manager.update_vod(vod_id, status=VodStatus.PENDING.value)
                reset_count += 1
            else:
                print(f"✗ VOD {vod_id} ({vod.streamer}) is not available")
                still_failed_count += 1

    print(f"\nDone: {reset_count} VODs reset to pending, {still_failed_count} still unavailable")


if __name__ == "__main__":
    main()
