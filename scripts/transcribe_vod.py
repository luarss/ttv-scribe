"""Script to transcribe a Twitch VOD and export transcript"""
import argparse
import logging
import sys

from src.state import StateManager, VodRecord, VodStatus, StreamerRecord, get_state_manager
from src.twitch.client import TwitchClient
from src.downloader import Downloader
from src.transcriber import create_transcriber, save_transcript_to_json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Transcribe a Twitch VOD")
    parser.add_argument("username", help="Twitch username")
    parser.add_argument("vod_id", help="VOD ID to transcribe")
    args = parser.parse_args()

    username = args.username
    vod_id = args.vod_id

    logger.info(f"Starting transcription for user={username}, vod_id={vod_id}")

    # Initialize state manager
    state = get_state_manager()

    # Get VOD info from Twitch
    client = TwitchClient()
    video = client.get_video_by_id(vod_id)

    if not video:
        logger.error(f"VOD {vod_id} not found")
        sys.exit(1)

    logger.info(f"Found VOD: {video.get('title', 'Untitled')}")

    # Get or create streamer in state
    streamer = state.get_streamer(username)
    if not streamer:
        streamer = StreamerRecord(
            username=username,
            twitch_id=str(video.get("user_id", "")),
        )
        state.add_streamer(streamer)
        logger.info(f"Created streamer: {username}")

    # Check if VOD already exists in state
    vod = state.get_vod(vod_id)
    if not vod:
        vod = VodRecord(
            vod_id=vod_id,
            streamer=username,
            title=video.get("title"),
            duration=video.get("duration"),
            recorded_at=video.get("created_at"),
            status=VodStatus.PENDING.value,
        )
        state.add_vod(vod)
        logger.info(f"Created VOD entry: {vod_id}")
    else:
        logger.info(f"Found existing VOD: {vod_id}")

    # Build vod_data dict for transcriber functions
    vod_data = {
        "vod_id": vod_id,
        "streamer": username,
        "title": video.get("title"),
        "duration": video.get("duration"),
        "recorded_at": video.get("created_at"),
    }

    # Download audio - update status to downloading
    downloader = Downloader()
    state.update_vod(vod_id, status=VodStatus.DOWNLOADING.value)

    audio_path = downloader.download_vod_audio(vod_data)
    logger.info(f"Downloaded audio to: {audio_path}")

    # Transcribe - update status to transcribing
    transcriber = create_transcriber()
    state.update_vod(vod_id, status=VodStatus.TRANSCRIBING.value)

    text, metadata, cost = transcriber.transcribe_vod(vod_data, audio_path)

    logger.info(f"Transcribed, cost: ${cost:.4f}")

    # Save transcript to JSON
    filepath = save_transcript_to_json(vod_data, text, metadata, cost)
    logger.info(f"Saved transcript to: {filepath}")

    # Update VOD status to completed with transcript path
    state.update_vod(
        vod_id,
        status=VodStatus.COMPLETED.value,
        transcript_path=filepath,
    )
    logger.info("Transcription complete!")

    print(f"TRANSCRIPT_FILE={filepath}")
    return filepath


if __name__ == "__main__":
    main()