"""CLI entry point for splitter job."""

import argparse
import json
import logging
import os

import yt_dlp

from src.distributed.splitter import (
    DEFAULT_CHUNK_DURATION,
    download_vod_audio,
    prepare_vod_chunks,
    save_chunk_manifest,
)
from src.state import VodStatus, get_state_manager

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Split VOD into chunks")
    parser.add_argument("vod_id", help="Twitch VOD ID")
    parser.add_argument(
        "--chunk-duration",
        type=int,
        default=DEFAULT_CHUNK_DURATION,
        help="Chunk duration in seconds (default: 600)",
    )
    parser.add_argument("--output-dir", default="./chunks", help="Output directory for chunks")
    args = parser.parse_args()

    # Download VOD
    try:
        audio_path, vod_data = download_vod_audio(args.vod_id)
    except yt_dlp.utils.DownloadError as e:
        # VOD no longer exists on Twitch
        logger.error(f"VOD {args.vod_id} not available on Twitch: {e}")
        manager = get_state_manager()
        manager.update_vod(args.vod_id, status=VodStatus.FAILED.value)
        # Output empty matrix so downstream jobs skip gracefully
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a") as f:
                f.write("num_chunks=0\n")
                f.write('matrix={"include": []}\n')
        print(f"VOD {args.vod_id} not available, skipping")
        return

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
