"""Local transcriber for VOD audio using faster-whisper"""
import logging

from faster_whisper import WhisperModel

from .config import get_settings
from .models import Vod

logger = logging.getLogger(__name__)


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

    def transcribe_vod(self, vod: Vod, audio_path: str) -> tuple[str, dict, float]:
        """Transcribe an audio file using local Whisper model

        Args:
            vod: The Vod object (unused for local, kept for interface compatibility)
            audio_path: Path to the audio file

        Returns:
            Tuple of (transcript_text, metadata, cost)

        Raises:
            Exception: If transcription fails
        """
        logger.info(f"Transcribing audio file: {audio_path}")

        # Run transcription
        segments, info = self.model.transcribe(
            audio_path,
            beam_size=5,
            vad_filter=True,  # Voice activity detection for better accuracy
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

        # Extract metadata - timestamps for key moments (every 5 minutes)
        metadata = self._extract_metadata(segment_list)

        # Local transcription is free
        cost = 0.0

        logger.info(
            f"Transcribed audio file, language: {info.language}, "
            f"duration: {info.duration:.2f}s, cost: ${cost:.4f}"
        )

        return full_text, metadata, cost

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