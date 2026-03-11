"""Script to transcribe a Twitch VOD and export transcript"""
import argparse
import logging
import sys
from datetime import datetime

from src.database import get_db_session, init_db
from src.models import Vod, Streamer, Transcript, VodStatus
from src.twitch.client import TwitchClient
from src.downloader import Downloader
from src.transcriber import create_transcriber, export_transcript_to_file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Transcribe a Twitch VOD")
    parser.add_argument("username", help="Twitch username")
    parser.add_argument("vod_id", help="VOD ID to transcribe")
    parser.add_argument("--output-dir", default="./transcripts", help="Output directory for transcripts")
    args = parser.parse_args()

    username = args.username
    vod_id = args.vod_id
    output_dir = args.output_dir

    logger.info(f"Starting transcription for user={username}, vod_id={vod_id}")

    # Initialize database
    init_db()

    # Get VOD info from Twitch
    client = TwitchClient()
    video = client.get_video_by_id(vod_id)

    if not video:
        logger.error(f"VOD {vod_id} not found")
        sys.exit(1)

    logger.info(f"Found VOD: {video.get('title', 'Untitled')}")

    # Get or create streamer and VOD in database
    with get_db_session() as session:
        streamer = session.query(Streamer).filter_by(username=username).first()
        if not streamer:
            streamer = Streamer(username=username)
            session.add(streamer)
            session.flush()
            logger.info(f"Created streamer: {username}")

        # Check if VOD already exists
        vod = session.query(Vod).filter_by(vod_id=vod_id).first()
        if not vod:
            created_at = video.get("created_at")
            if created_at:
                created_at = created_at.replace("Z", "+00:00")
                recorded_at = datetime.fromisoformat(created_at)
            else:
                recorded_at = None

            vod = Vod(
                vod_id=vod_id,
                streamer_id=streamer.id,
                title=video.get("title"),
                duration=video.get("duration"),
                recorded_at=recorded_at,
                status=VodStatus.PENDING,
            )
            session.add(vod)
            session.flush()
            logger.info(f"Created VOD entry: {vod_id}")
        else:
            logger.info(f"Found existing VOD: {vod_id}")

    # Download audio
    downloader = Downloader()
    with get_db_session() as session:
        vod = session.query(Vod).filter_by(vod_id=vod_id).first()
        vod.status = VodStatus.DOWNLOADING
        session.flush()

        # Pass vod_id instead of Vod object
        audio_path = downloader.download_vod_audio(vod_id)

    logger.info(f"Downloaded audio to: {audio_path}")

    # Transcribe
    transcriber = create_transcriber()
    with get_db_session() as session:
        vod = session.query(Vod).filter_by(vod_id=vod_id).first()
        vod.status = VodStatus.TRANSCRIBING
        session.flush()

        text, metadata, cost = transcriber.transcribe_vod(vod_id, audio_path)

    logger.info(f"Transcribed, cost: ${cost:.4f}")

    # Save transcript to database
    with get_db_session() as session:
        vod = session.query(Vod).filter_by(vod_id=vod_id).first()
        transcript = Transcript(
            vod_id=vod.id,
            text=text,
            transcript_metadata=metadata,
            cost=cost,
        )
        session.add(transcript)
        vod.status = VodStatus.COMPLETED
        logger.info("Saved transcript to database")

    # Export to file
    filepath = export_transcript_to_file(vod_id, output_dir=output_dir)
    logger.info(f"Exported transcript to: {filepath}")

    # Cleanup audio
    downloader.cleanup_audio(audio_path)
    logger.info("Transcription complete!")

    print(f"TRANSCRIPT_FILE={filepath}")
    return filepath


if __name__ == "__main__":
    main()