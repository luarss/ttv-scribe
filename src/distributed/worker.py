"""Worker for transcribing a single audio chunk"""

import json
import logging
import time
from typing import Optional

from faster_whisper import WhisperModel

from ..config import get_settings

logger = logging.getLogger(__name__)


def transcribe_chunk(
    chunk_path: str,
    chunk_index: int,
    chunk_duration: int,
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    compute_type: Optional[str] = None,
    beam_size: Optional[int] = None,
    vad_min_silence_ms: Optional[int] = None,
) -> dict:
    """Transcribe a single audio chunk with timestamp offset

    Args:
        chunk_path: Path to the chunk audio file
        chunk_index: Index of this chunk (0-based)
        chunk_duration: Expected duration of each chunk in seconds
        model_name: Whisper model name (default: from settings)
        device: Device for inference (default: from settings)
        compute_type: Compute type (default: from settings)
        beam_size: Beam size for transcription (default: from settings)
        vad_min_silence_ms: VAD min silence duration (default: from settings)

    Returns:
        Dict with:
            - chunk_index: int
            - segments: list of {start, end, text}
            - text: str (combined text)
            - language: str
            - duration: float
            - elapsed: float
    """
    settings = get_settings()

    # Use provided args or fall back to settings
    model_name = model_name or settings.whisper_model
    device = device or settings.whisper_device
    compute_type = compute_type or settings.whisper_compute_type
    beam_size = beam_size or settings.whisper_beam_size
    vad_min_silence_ms = vad_min_silence_ms or settings.whisper_vad_min_silence_ms

    logger.info(f"Loading Whisper model: {model_name} ({device}/{compute_type})")
    model = WhisperModel(model_name, device=device, compute_type=compute_type)

    start_time = time.time()
    logger.info(f"Transcribing chunk {chunk_index}: {chunk_path}")

    segments, info = model.transcribe(
        chunk_path,
        beam_size=beam_size,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=vad_min_silence_ms),
    )

    # Calculate offset for this chunk
    offset = chunk_index * chunk_duration

    # Collect segments with offset adjustment
    segment_list = []
    text_parts = []

    for segment in segments:
        adjusted_start = segment.start + offset
        adjusted_end = segment.end + offset

        segment_list.append({
            "start": adjusted_start,
            "end": adjusted_end,
            "text": segment.text,
        })
        text_parts.append(segment.text)

    elapsed = time.time() - start_time

    result = {
        "chunk_index": chunk_index,
        "segments": segment_list,
        "text": "".join(text_parts).strip(),
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration if info.duration else 0,
        "elapsed": elapsed,
    }

    logger.info(
        f"Chunk {chunk_index} done: {len(segment_list)} segments, "
        f"{info.duration:.0f}s audio in {elapsed:.1f}s"
    )

    return result


def save_chunk_result(result: dict, output_path: str) -> str:
    """Save chunk transcription result to JSON file

    Args:
        result: The result dict from transcribe_chunk
        output_path: Path to save the result

    Returns:
        Path to the saved result file
    """
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved chunk result to {output_path}")
    return output_path


