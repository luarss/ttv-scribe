"""Assembler for merging chunk transcription results into final transcript"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..config import get_settings
from ..state import get_state_manager, VodStatus

logger = logging.getLogger(__name__)


def load_chunk_result(result_path: str) -> dict:
    """Load a chunk transcription result from JSON file

    Args:
        result_path: Path to the result JSON file

    Returns:
        The chunk result dict
    """
    with open(result_path, "r") as f:
        return json.load(f)


def assemble_transcript(
    vod_id: str,
    streamer: str,
    title: Optional[str],
    recorded_at: Optional[str],
    total_duration: float,
    chunk_results: list[dict],
) -> dict:
    """Assemble chunk results into final transcript

    Args:
        vod_id: The Twitch VOD ID
        streamer: Streamer username
        title: VOD title
        recorded_at: ISO datetime when VOD was recorded
        total_duration: Total audio duration in seconds
        chunk_results: List of chunk result dicts from workers

    Returns:
        Complete transcript dict ready for saving
    """
    # Sort results by chunk index
    chunk_results = sorted(chunk_results, key=lambda x: x["chunk_index"])

    # Merge all segments
    all_segments = []
    for result in chunk_results:
        all_segments.extend(result["segments"])

    # Sort by start time (should already be in order, but ensure it)
    all_segments.sort(key=lambda x: x["start"])

    # Combine text
    full_text = "".join(seg["text"] for seg in all_segments).strip()

    # Extract metadata
    metadata = {
        "segments_count": len(all_segments),
        "total_duration_seconds": total_duration,
        "chunks": len(chunk_results),
        "chunk_transcription_times": [r["elapsed"] for r in chunk_results],
        "languages": list(set(r.get("language", "unknown") for r in chunk_results)),
        "key_moments": _extract_key_moments(all_segments),
    }

    transcript = {
        "vod_id": vod_id,
        "streamer": streamer,
        "title": title,
        "recorded_at": recorded_at,
        "text": full_text,
        "metadata": metadata,
        "segments": all_segments,
        "cost": 0.0,  # Local transcription is free
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    logger.info(
        f"Assembled transcript: {len(all_segments)} segments, "
        f"{len(full_text)} chars, {total_duration:.0f}s audio"
    )

    return transcript


def _extract_key_moments(segments: list[dict], interval: int = 300) -> list[dict]:
    """Extract key moments at regular intervals (every 5 minutes by default)"""
    key_moments = []
    last_interval = -1

    for segment in segments:
        start = segment.get("start", 0)
        current_interval = int(start // interval)

        # Add key moment when we cross into a new interval
        if current_interval > last_interval and start > 0:
            key_moments.append({
                "time": int(start),
                "text": segment.get("text", "").strip()[:200],
            })
            last_interval = current_interval

    return key_moments


def save_transcript(transcript: dict, output_dir: Optional[str] = None) -> str:
    """Save assembled transcript to JSON file

    Args:
        transcript: The assembled transcript dict
        output_dir: Output directory (default: from settings)

    Returns:
        Path to the saved transcript file
    """
    settings = get_settings()
    transcript_dir = output_dir or settings.transcript_dir

    streamer = transcript["streamer"]
    vod_id = transcript["vod_id"]

    # Create output directory: ./transcripts/<username>/
    streamer_dir = os.path.join(transcript_dir, streamer)
    os.makedirs(streamer_dir, exist_ok=True)

    # Use VOD ID as filename
    filepath = os.path.join(streamer_dir, f"{vod_id}.json")

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved transcript to {filepath}")
    return filepath


def update_vod_status(vod_id: str, transcript_path: str, status: str = "completed"):
    """Update VOD status in state after successful transcription

    Args:
        vod_id: The Twitch VOD ID
        transcript_path: Path to the saved transcript
        status: New status (default: completed)
    """
    manager = get_state_manager()
    manager.update_vod(
        vod_id,
        status=status,
        transcript_path=transcript_path,
    )
    logger.info(f"Updated VOD {vod_id} status to {status}")


def load_chunk_results_from_dir(results_dir: str) -> list[dict]:
    """Load all chunk results from a directory

    Args:
        results_dir: Directory containing result-*.json files

    Returns:
        List of chunk result dicts
    """
    chunk_results = []
    results_path = Path(results_dir)

    for result_file in sorted(results_path.glob("result-*.json")):
        result = load_chunk_result(str(result_file))
        chunk_results.append(result)
        logger.info(f"Loaded chunk {result['chunk_index']} result")

    return chunk_results


def main():
    """CLI entry point for assembler job"""
    import argparse

    parser = argparse.ArgumentParser(description="Assemble chunk results into transcript")
    parser.add_argument("--vod-id", required=True, help="Twitch VOD ID")
    parser.add_argument("--streamer", required=True, help="Streamer username")
    parser.add_argument("--title", default=None, help="VOD title")
    parser.add_argument("--recorded-at", default=None, help="ISO datetime")
    parser.add_argument("--total-duration", type=float, required=True,
                        help="Total audio duration in seconds")
    parser.add_argument("--results-dir", default="./results",
                        help="Directory containing chunk result files")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory for final transcript")
    args = parser.parse_args()

    # Load all chunk results
    chunk_results = load_chunk_results_from_dir(args.results_dir)

    if not chunk_results:
        logger.error("No chunk results found!")
        return 1

    # Assemble transcript
    transcript = assemble_transcript(
        vod_id=args.vod_id,
        streamer=args.streamer,
        title=args.title,
        recorded_at=args.recorded_at,
        total_duration=args.total_duration,
        chunk_results=chunk_results,
    )

    # Save transcript
    transcript_path = save_transcript(transcript, args.output_dir)

    # Update VOD status
    update_vod_status(args.vod_id, transcript_path, VodStatus.COMPLETED.value)

    # Output for GitHub Actions
    github_output = os.environ.get("GITHUB_OUTPUT")
    outputs = {
        "transcript_path": transcript_path,
        "segments_count": transcript["metadata"]["segments_count"],
    }

    if github_output:
        with open(github_output, "a") as f:
            for key, value in outputs.items():
                f.write(f"{key}={value}\n")
    else:
        for key, value in outputs.items():
            print(f"{key}={value}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    exit(main())
