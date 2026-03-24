"""Split VOD audio into chunks for distributed transcription"""

import json
import logging
import os
import tempfile
from typing import Any, Optional

from ..audio_utils import split_audio_chunks, get_audio_duration
from ..downloader import Downloader
from ..state import get_state_manager, VodStatus

logger = logging.getLogger(__name__)

# Default chunk duration: 10 minutes
DEFAULT_CHUNK_DURATION = 600


def download_vod_audio(vod_id: str) -> tuple[str, dict[str, Any]]:
    """Download VOD audio and return path + VOD metadata

    Args:
        vod_id: The Twitch VOD ID

    Returns:
        Tuple of (audio_path, vod_data)

    Raises:
        ValueError: If VOD not found in state
        RuntimeError: If download fails
    """
    manager = get_state_manager()
    vod_record = manager.get_vod(vod_id)

    if not vod_record:
        raise ValueError(f"VOD {vod_id} not found in state")

    # Convert VodRecord to dict
    vod_data = vod_record.to_dict()

    # Update status to indicate we're processing
    manager.update_vod(vod_id, status=VodStatus.TRANSCRIBING.value)

    downloader = Downloader()
    audio_path = downloader.download_vod_audio(vod_data)

    return audio_path, vod_data


def prepare_vod_chunks(
    vod_id: str,
    audio_path: str,
    vod_data: dict,
    chunk_duration: int = DEFAULT_CHUNK_DURATION,
    output_dir: Optional[str] = None,
) -> dict[str, Any]:
    """Split VOD audio into chunks for distributed transcription

    Args:
        vod_id: The Twitch VOD ID
        audio_path: Path to the downloaded audio file
        vod_data: VOD metadata dict
        chunk_duration: Duration of each chunk in seconds (default: 600 = 10 min)
        output_dir: Directory to store chunks. If None, uses temp directory.

    Returns:
        Dict with:
            - vod_id: str
            - streamer: str
            - title: str
            - recorded_at: str
            - total_duration: float
            - chunk_duration: int
            - chunks: list of {index, path, start_time, duration}
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix=f"vod_chunks_{vod_id}_")
    else:
        os.makedirs(output_dir, exist_ok=True)

    # Get total audio duration
    total_duration = get_audio_duration(audio_path)
    logger.info(f"VOD {vod_id} duration: {total_duration:.0f}s ({total_duration/60:.1f} min)")

    # Split into chunks
    chunk_paths = split_audio_chunks(
        audio_path,
        chunk_duration_seconds=chunk_duration,
        output_dir=output_dir,
    )

    # Build chunk metadata
    chunks = []
    for i, path in enumerate(chunk_paths):
        chunk_dur = get_audio_duration(path)
        # Handle last chunk being shorter
        actual_duration = min(chunk_dur, chunk_duration)
        chunks.append({
            "index": i,
            "path": path,
            "start_time": i * chunk_duration,
            "duration": actual_duration,
        })

    logger.info(f"Split VOD {vod_id} into {len(chunks)} chunks")

    return {
        "vod_id": vod_id,
        "streamer": vod_data.get("streamer", "unknown"),
        "title": vod_data.get("title"),
        "recorded_at": vod_data.get("recorded_at"),
        "total_duration": total_duration,
        "chunk_duration": chunk_duration,
        "chunks": chunks,
    }


def save_chunk_manifest(manifest: dict, output_path: str) -> str:
    """Save chunk manifest to JSON file

    Args:
        manifest: The manifest dict from prepare_vod_chunks
        output_path: Path to save the manifest

    Returns:
        Path to the saved manifest file
    """
    # Create a serializable version (without file paths for workers)
    serializable = {
        "vod_id": manifest["vod_id"],
        "streamer": manifest["streamer"],
        "title": manifest["title"],
        "recorded_at": manifest["recorded_at"],
        "total_duration": manifest["total_duration"],
        "chunk_duration": manifest["chunk_duration"],
        "num_chunks": len(manifest["chunks"]),
    }

    with open(output_path, "w") as f:
        json.dump(serializable, f, indent=2)

    logger.info(f"Saved chunk manifest to {output_path}")
    return output_path


def main():
    """CLI entry point for splitter job"""
    import argparse

    parser = argparse.ArgumentParser(description="Split VOD into chunks")
    parser.add_argument("vod_id", help="Twitch VOD ID")
    parser.add_argument("--chunk-duration", type=int, default=DEFAULT_CHUNK_DURATION,
                        help="Chunk duration in seconds (default: 600)")
    parser.add_argument("--output-dir", default="./chunks",
                        help="Output directory for chunks")
    args = parser.parse_args()

    # Download VOD
    audio_path, vod_data = download_vod_audio(args.vod_id)

    # Split into chunks
    manifest = prepare_vod_chunks(
        args.vod_id,
        audio_path,
        vod_data,
        chunk_duration=args.chunk_duration,
        output_dir=args.output_dir,
    )

    # Save manifest
    save_chunk_manifest(manifest, f"{args.output_dir}/manifest.json")

    # Output matrix for GitHub Actions
    # Each chunk gets: {index, start_time, duration}
    matrix = [
        {
            "index": c["index"],
            "start_time": c["start_time"],
            "duration": c["duration"],
        }
        for c in manifest["chunks"]
    ]

    # Output for GitHub Actions (using GITHUB_OUTPUT file)
    # Use heredoc format for values that may contain special characters
    github_output = os.environ.get("GITHUB_OUTPUT")
    delimiter = "ghadelimiter"

    # Outputs that can use simple format (no special characters)
    # Wrap matrix in {"include": [...]} for GitHub Actions matrix syntax
    matrix_json = json.dumps({"include": matrix})
    title = manifest["title"] or ""
    recorded_at = manifest["recorded_at"] or ""

    if github_output:
        with open(github_output, "a") as f:
            # Simple outputs (single line, no special chars)
            f.write(f"num_chunks={len(matrix)}\n")
            f.write(f"vod_id={args.vod_id}\n")
            f.write(f"streamer={manifest['streamer']}\n")
            f.write(f"total_duration={manifest['total_duration']}\n")
            # Matrix uses simple format (JSON has no special chars that break parsing)
            f.write(f"matrix={matrix_json}\n")
            # Heredoc format for title/recorded_at (may contain |, !, emojis, etc.)
            f.write(f"title<<{delimiter}\n{title}\n{delimiter}\n")
            f.write(f"recorded_at<<{delimiter}\n{recorded_at}\n{delimiter}\n")
    else:
        print(f"num_chunks={len(matrix)}")
        print(f"vod_id={args.vod_id}")
        print(f"streamer={manifest['streamer']}")
        print(f"total_duration={manifest['total_duration']}")
        print(f"matrix={matrix_json}")
        print(f"title={title}")
        print(f"recorded_at={recorded_at}")

    print(f"Prepared {len(matrix)} chunks for VOD {args.vod_id}")

    # Cleanup original audio (chunks remain)
    os.remove(audio_path)
    logger.info(f"Cleaned up original audio: {audio_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
