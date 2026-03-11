"""Transcriber for VOD audio using OpenAI Whisper"""
import json
import logging
import os
from datetime import datetime, timezone

import openai

from .config import get_settings
from .state import (
    get_downloading_vods,
    get_state_manager,
    VodStatus,
)

logger = logging.getLogger(__name__)


class Transcriber:
    """Transcriber using OpenAI Whisper API"""

    def __init__(self):
        self.settings = get_settings()
        openai.api_key = self.settings.openai_api_key

    def transcribe_vod(self, vod_data: dict, audio_path: str) -> tuple[str, dict, float]:
        """Transcribe a VOD's audio

        Args:
            vod_data: The VOD data dictionary
            audio_path: Path to the audio file

        Returns:
            Tuple of (transcript_text, metadata, cost)

        Raises:
            Exception: If transcription fails
        """
        vod_id = vod_data["vod_id"]
        duration = vod_data.get("duration")

        logger.info(f"Transcribing VOD {vod_id}")

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


def save_transcript_to_json(
    vod_data: dict,
    text: str,
    metadata: dict,
    cost: float,
) -> str:
    """Save transcript as JSON file

    Args:
        vod_data: The VOD data dictionary
        text: The transcript text
        metadata: The transcript metadata
        cost: The transcription cost

    Returns:
        Path to the saved transcript file
    """
    settings = get_settings()
    transcript_dir = settings.transcript_dir

    streamer = vod_data.get("streamer", "unknown")
    vod_id = vod_data["vod_id"]

    # Create output directory: ./transcripts/<username>/
    streamer_dir = os.path.join(transcript_dir, streamer)
    os.makedirs(streamer_dir, exist_ok=True)

    # Use VOD ID as filename
    filepath = os.path.join(streamer_dir, f"{vod_id}.json")

    # Build transcript data
    transcript_data = {
        "vod_id": vod_id,
        "streamer": streamer,
        "title": vod_data.get("title"),
        "recorded_at": vod_data.get("recorded_at"),
        "text": text,
        "metadata": metadata,
        "cost": cost,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    # Write to JSON file
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(transcript_data, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved transcript to {filepath}")
    return filepath


def export_transcript_to_text(
    vod_data: dict,
    text: str,
    output_dir: str = "./transcripts",
) -> str:
    """Export transcript to a text file

    Args:
        vod_data: The VOD data dictionary
        text: The transcript text
        output_dir: Base directory for transcript output

    Returns:
        Path to the created transcript file
    """
    streamer = vod_data.get("streamer", "unknown")
    vod_id = vod_data["vod_id"]
    title = vod_data.get("title")

    # Create output directory: ./transcripts/<username>/
    user_dir = os.path.join(output_dir, streamer, "text")
    os.makedirs(user_dir, exist_ok=True)

    # Use VOD ID as filename (or sanitize title if available)
    filename = f"{vod_id}.txt"
    if title:
        # Sanitize title for use as filename
        sanitized = "".join(c for c in title if c.isalnum() or c in " -_").strip()
        sanitized = sanitized[:100]  # Limit length
        filename = f"{sanitized}.txt"

    filepath = os.path.join(user_dir, filename)

    # Write transcript to file
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(text)

    logger.info(f"Exported transcript to {filepath}")
    return filepath


def process_downloaded_vods() -> int:
    """Process all downloaded VODs awaiting transcription

    Returns:
        Number of VODs transcribed
    """
    from .downloader import Downloader

    processed = 0
    transcriber = create_transcriber()
    downloader = Downloader()
    manager = get_state_manager()

    # Get all VODs that have been downloaded (status = DOWNLOADING)
    downloading_vods = get_downloading_vods()

    for vod_data in downloading_vods:
        vod_id = vod_data["vod_id"]
        try:
            # Update status to TRANSCRIBING
            manager.update_vod(vod_id, status=VodStatus.TRANSCRIBING.value)

            # Download audio (if not already downloaded)
            audio_path = downloader.download_vod_audio(vod_data)

            # Transcribe
            text, metadata, cost = transcriber.transcribe_vod(vod_data, audio_path)

            # Save transcript as JSON
            transcript_path = save_transcript_to_json(vod_data, text, metadata, cost)

            # Also export to text file for compatibility
            export_transcript_to_text(vod_data, text)

            # Update VOD record with transcript path and mark as completed
            manager.update_vod(
                vod_id,
                status=VodStatus.COMPLETED.value,
                transcript_path=transcript_path,
            )

            # Cleanup audio
            downloader.cleanup_audio(audio_path)

            processed += 1
            logger.info(f"Completed transcription for VOD {vod_id}")

        except Exception as e:
            logger.error(f"Failed to transcribe VOD {vod_id}: {e}")
            manager.update_vod(vod_id, status=VodStatus.FAILED.value)

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
