"""Local transcriber for VOD audio using faster-whisper"""
import json
import logging
import os
import tempfile
from datetime import datetime, timezone

from faster_whisper import WhisperModel

from .audio_utils import split_audio_chunks, cleanup_chunks, get_audio_duration
from .config import get_settings
from .state import (
    get_downloading_vods,
    get_state_manager,
    VodStatus,
)

logger = logging.getLogger(__name__)

# Maximum chunk duration in seconds (30 minutes)
DEFAULT_CHUNK_DURATION = 30 * 60


class LocalTranscriber:
    """Transcriber using local faster-whisper model"""

    def __init__(self):
        self.settings = get_settings()
        self._model = None

    @property
    def model(self) -> WhisperModel:
        """Lazy-load the Whisper model"""
        if self._model is None:
            logger.info(
                f"Loading faster-whisper model: {self.settings.whisper_model} "
                f"({self.settings.whisper_device}/{self.settings.whisper_compute_type})"
            )
            self._model = WhisperModel(
                self.settings.whisper_model,
                device=self.settings.whisper_device,
                compute_type=self.settings.whisper_compute_type,
            )
        return self._model

    def transcribe_vod(
        self,
        vod_data: dict,
        audio_path: str,
        max_chunk_duration: int = DEFAULT_CHUNK_DURATION,
    ) -> tuple[str, dict, float]:
        """Transcribe an audio file using local Whisper model

        Args:
            vod_data: The VOD data dictionary (must contain vod_id)
            audio_path: Path to the audio file
            max_chunk_duration: Maximum chunk duration in seconds (default: 30 minutes)

        Returns:
            Tuple of (transcript_text, metadata, cost)

        Raises:
            Exception: If transcription fails
        """
        vod_id = vod_data.get("vod_id", "unknown")
        logger.info(f"Transcribing audio file: {audio_path}")

        # Check if we need to chunk the audio
        audio_duration = get_audio_duration(audio_path)
        chunk_paths = []
        chunk_dir = None

        try:
            if audio_duration > max_chunk_duration:
                # Split into chunks
                logger.info(f"Audio duration {audio_duration:.0f}s exceeds {max_chunk_duration}s, splitting into chunks")
                chunk_dir = tempfile.mkdtemp(prefix="whisper_chunks_")
                chunk_paths = split_audio_chunks(
                    audio_path,
                    chunk_duration_seconds=max_chunk_duration,
                    output_dir=chunk_dir,
                )
                logger.info(f"Split into {len(chunk_paths)} chunks")

                # Transcribe each chunk and combine results
                all_text_parts = []
                all_segments = []
                total_duration = 0.0
                chunk_num = 0

                for chunk_path in chunk_paths:
                    chunk_num += 1
                    logger.info(f"Transcribing chunk {chunk_num}/{len(chunk_paths)}: {chunk_path}")

                    segments, info = self.model.transcribe(
                        chunk_path,
                        beam_size=5,
                        vad_filter=True,
                        vad_parameters=dict(min_silence_duration_ms=500),
                    )

                    chunk_text_parts = []
                    for segment in segments:
                        # Adjust timestamps by adding offset from chunk start
                        offset = (chunk_num - 1) * max_chunk_duration
                        all_segments.append({
                            "start": segment.start + offset,
                            "end": segment.end + offset,
                            "text": segment.text,
                        })
                        chunk_text_parts.append(segment.text)

                    all_text_parts.extend(chunk_text_parts)
                    total_duration += info.duration if info.duration else 0

                full_text = "".join(all_text_parts).strip()

                # Use combined segments for metadata
                metadata = self._extract_metadata(all_segments)
                metadata["chunks"] = len(chunk_paths)
                metadata["total_duration_seconds"] = audio_duration

                # Log combined results
                logger.info(
                    f"Transcribed {len(chunk_paths)} chunks, total duration: {total_duration:.2f}s"
                )
            else:
                # Direct transcription for short audio
                segments, info = self.model.transcribe(
                    audio_path,
                    beam_size=5,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=500),
                )

                # Collect all text
                text_parts = []
                segment_list = []
                for segment in segments:
                    text_parts.append(segment.text)
                    segment_list.append({
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text,
                    })

                full_text = "".join(text_parts).strip()
                metadata = self._extract_metadata(segment_list)
                metadata["total_duration_seconds"] = audio_duration

                logger.info(
                    f"Transcribed audio file, language: {info.language}, "
                    f"duration: {info.duration:.2f}s"
                )

            # Local transcription is free
            cost = 0.0

            return full_text, metadata, cost

        finally:
            # Cleanup chunk files if we created them (pass original to preserve it)
            if chunk_paths:
                cleanup_chunks(chunk_paths, original_path=audio_path)
                # Cleanup chunk directory
                if chunk_dir:
                    try:
                        if os.path.exists(chunk_dir):
                            os.rmdir(chunk_dir)
                    except Exception as e:
                        logger.warning(f"Failed to cleanup chunk directory: {e}")

    def _extract_metadata(self, segments: list[dict]) -> dict:
        """Extract useful metadata from transcription segments"""
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
    transcriber = LocalTranscriber()
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
    """Factory function to create the transcriber (always returns LocalTranscriber)

    Returns:
        LocalTranscriber instance
    """
    logger.info("Using local Whisper transcriber")
    return LocalTranscriber()