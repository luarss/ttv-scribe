"""Transcriber for VOD audio using OpenAI Whisper"""
import logging
import os

import openai

from .config import get_settings
from .database import get_db_session
from .models import Vod, Transcript, VodStatus

logger = logging.getLogger(__name__)


class Transcriber:
    """Transcriber using OpenAI Whisper API"""

    def __init__(self):
        self.settings = get_settings()
        openai.api_key = self.settings.openai_api_key

    def transcribe_vod(self, vod_id: str, audio_path: str) -> tuple[str, dict, float]:
        """Transcribe a VOD's audio

        Args:
            vod_id: The VOD ID to transcribe
            audio_path: Path to the audio file

        Returns:
            Tuple of (transcript_text, metadata, cost)

        Raises:
            Exception: If transcription fails
        """
        logger.info(f"Transcribing VOD {vod_id}")

        # Get VOD duration from database
        with get_db_session() as session:
            vod = session.query(Vod).filter_by(vod_id=vod_id).first()
            duration = vod.duration if vod else 0

        with open(audio_path, "rb") as audio_file:
            response = openai.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

        # Extract text
        text = response.text

        # Extract metadata - timestamps for key moments (every 5 minutes)
        metadata = self._extract_metadata(response)

        # Estimate cost (Whisper pricing: $0.006/minute for audio)
        cost = (duration / 60) * 0.006 if duration else 0.0

        logger.info(f"Transcribed VOD {vod_id}, cost: ${cost:.4f}")

        return text, metadata, cost

    def _extract_metadata(self, response) -> dict:
        """Extract useful metadata from transcription response"""
        segments = getattr(response, "segments", [])

        if not segments:
            return {}

        # Extract timestamp key moments (every 5 minutes / 300 seconds)
        key_moments = []
        for segment in segments:
            start = segment.get("start", 0)
            # Add key moment at 5-minute intervals
            if start > 0 and start % 300 < 5:
                key_moments.append({
                    "time": int(start),
                    "text": segment.get("text", "").strip()[:200],
                })

        return {
            "segments_count": len(segments),
            "key_moments": key_moments,
        }


def process_downloaded_vods() -> int:
    """Process all downloaded VODs awaiting transcription

    Returns:
        Number of VODs transcribed
    """
    from .downloader import Downloader

    processed = 0
    transcriber = create_transcriber()
    downloader = Downloader()

    with get_db_session() as session:
        # Find VODs that have been downloaded (in a real app, we'd track this)
        # For MVP, we'll just process VODs with duration
        pending = session.query(Vod).filter(
            Vod.status == VodStatus.DOWNLOADING,
            Vod.duration.isnot(None),
        ).all()

        for vod in pending:
            try:
                # Update status
                vod.status = VodStatus.TRANSCRIBING

                # Download audio
                audio_path = downloader.download_vod_audio(vod)

                # Transcribe
                text, metadata, cost = transcriber.transcribe_vod(vod, audio_path)

                # Save transcript
                transcript = Transcript(
                    vod_id=vod.id,
                    text=text,
                    transcript_metadata=metadata,
                    cost=cost,
                )
                session.add(transcript)

                # Mark as completed
                vod.status = VodStatus.COMPLETED

                # Cleanup audio
                downloader.cleanup_audio(audio_path)

                processed += 1
                logger.info(f"Completed transcription for VOD {vod.vod_id}")

            except Exception as e:
                logger.error(f"Failed to transcribe VOD {vod.vod_id}: {e}")
                vod.status = VodStatus.FAILED

    return processed


def create_transcriber():
    """Factory function to create the appropriate transcriber based on settings

    Returns:
        Transcriber instance (API or local)
    """
    settings = get_settings()

    if settings.whisper_use_local:
        from .transcriber_local import LocalTranscriber
        logger.info("Using local Whisper transcriber")
        return LocalTranscriber()
    else:
        logger.info("Using OpenAI Whisper API transcriber")
        return Transcriber()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = process_downloaded_vods()
    logger.info(f"Transcribed {count} VODs")


def export_transcript_to_file(vod_id: str, output_dir: str = "./transcripts") -> str:
    """Export transcript to a text file

    Args:
        vod_id: The VOD ID to export transcript for
        output_dir: Base directory for transcript output

    Returns:
        Path to the created transcript file

    Raises:
        ValueError: If no transcript exists for the VOD
    """
    with get_db_session() as session:
        vod = session.query(Vod).filter_by(vod_id=vod_id).first()

        if not vod:
            raise ValueError(f"VOD {vod_id} not found")

        if not vod.transcript:
            raise ValueError(f"No transcript found for VOD {vod_id}")

        # Get the streamer's username
        username = vod.streamer.username if vod.streamer else "unknown"

        # Create output directory: ./transcripts/<username>/
        user_dir = os.path.join(output_dir, username)
        os.makedirs(user_dir, exist_ok=True)

        # Use VOD ID as filename for cleaner names
        filename = f"{vod.vod_id}.txt"

        filepath = os.path.join(user_dir, filename)

        # Write transcript to file
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(vod.transcript.text)

        logger.info(f"Exported transcript to {filepath}")
        return filepath