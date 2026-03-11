"""Audio utilities for splitting long audio files into chunks"""
import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def split_audio_chunks(
    audio_path: str,
    chunk_duration_seconds: int = 1800,
    output_dir: str | None = None,
) -> list[str]:
    """Split an audio file into chunks of specified duration

    Args:
        audio_path: Path to the input audio file
        chunk_duration_seconds: Duration of each chunk in seconds (default: 30 minutes)
        output_dir: Directory to store chunk files. If None, uses temp directory.

    Returns:
        List of paths to chunk files
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="audio_chunks_")
    else:
        os.makedirs(output_dir, exist_ok=True)

    # Get audio duration using ffprobe
    duration = get_audio_duration(audio_path)
    logger.info(f"Audio duration: {duration:.2f}s, splitting into {chunk_duration_seconds}s chunks")

    if duration <= chunk_duration_seconds:
        # No splitting needed, return original file
        return [audio_path]

    # Calculate number of chunks
    num_chunks = int(duration // chunk_duration_seconds) + (1 if duration % chunk_duration_seconds > 0 else 0)

    chunk_paths = []
    base_name = Path(audio_path).stem

    for i in range(num_chunks):
        start_time = i * chunk_duration_seconds
        chunk_filename = f"{base_name}_chunk_{i+1:03d}.mp3"
        chunk_path = os.path.join(output_dir, chunk_filename)

        # Use ffmpeg to extract chunk
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", audio_path,
            "-ss", str(start_time),
            "-t", str(chunk_duration_seconds),
            "-acodec", "copy",  # Copy audio without re-encoding for speed
            chunk_path,
        ]

        logger.debug(f"Creating chunk {i+1}/{num_chunks}: {chunk_path}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.warning(f"ffmpeg failed for chunk {i+1}, trying with re-encoding: {result.stderr}")
            # Fallback: re-encode the chunk
            cmd = [
                "ffmpeg",
                "-y",
                "-i", audio_path,
                "-ss", str(start_time),
                "-t", str(chunk_duration_seconds),
                "-acodec", "libmp3lame",
                "-ab", "192k",
                chunk_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to create chunk {i+1}: {result.stderr}")
                continue

        if os.path.exists(chunk_path):
            chunk_paths.append(chunk_path)
            logger.info(f"Created chunk {i+1}/{num_chunks}: {os.path.getsize(chunk_path) / 1024 / 1024:.2f}MB")

    logger.info(f"Created {len(chunk_paths)} audio chunks")
    return chunk_paths


def get_audio_duration(audio_path: str) -> float:
    """Get the duration of an audio file using ffprobe

    Args:
        audio_path: Path to the audio file

    Returns:
        Duration in seconds
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    try:
        return float(result.stdout.strip())
    except ValueError:
        raise RuntimeError(f"Could not parse duration from ffprobe output: {result.stdout}")


def cleanup_chunks(chunk_paths: list[str], original_path: str | None = None):
    """Clean up chunk files (except the original audio file)

    Args:
        chunk_paths: List of chunk file paths to delete
        original_path: Path to the original audio file (will not be deleted)
    """
    for path in chunk_paths:
        try:
            # Skip cleanup if this is the original file
            if original_path and path == original_path:
                continue
            if os.path.exists(path):
                os.remove(path)
                logger.debug(f"Cleaned up chunk: {path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup chunk {path}: {e}")