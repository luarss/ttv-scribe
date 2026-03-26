"""CLI entry point for assembler job."""

import argparse
import logging
import os

from src.distributed.assembler import (
    assemble_transcript,
    load_chunk_results_from_dir,
    save_transcript,
    update_vod_status,
)
from src.state import VodStatus

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Assemble chunk results into transcript")
    parser.add_argument("--vod-id", required=True, help="Twitch VOD ID")
    parser.add_argument("--streamer", required=True, help="Streamer username")
    parser.add_argument("--title", default=None, help="VOD title")
    parser.add_argument("--recorded-at", default=None, help="ISO datetime")
    parser.add_argument(
        "--total-duration",
        type=float,
        required=True,
        help="Total audio duration in seconds",
    )
    parser.add_argument(
        "--results-dir",
        default="./results",
        help="Directory containing chunk result files",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for final transcript",
    )
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
