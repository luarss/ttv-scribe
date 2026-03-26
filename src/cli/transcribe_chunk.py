"""CLI entry point for worker job."""

import argparse
import json
import logging
import os

from src.distributed.worker import save_chunk_result, transcribe_chunk

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Transcribe a single chunk")
    parser.add_argument("chunk_path", help="Path to chunk audio file")
    parser.add_argument(
        "--chunk-index",
        type=int,
        required=True,
        help="Index of this chunk (0-based)",
    )
    parser.add_argument(
        "--chunk-duration",
        type=int,
        required=True,
        help="Duration of each chunk in seconds",
    )
    parser.add_argument(
        "--output",
        default="./result.json",
        help="Output path for result JSON",
    )
    args = parser.parse_args()

    result = transcribe_chunk(
        chunk_path=args.chunk_path,
        chunk_index=args.chunk_index,
        chunk_duration=args.chunk_duration,
    )

    save_chunk_result(result, args.output)

    # Output summary for GitHub Actions
    github_output = os.environ.get("GITHUB_OUTPUT")
    outputs = {
        "chunk_index": result["chunk_index"],
        "segments_count": len(result["segments"]),
        "duration": result["duration"],
        "elapsed": result["elapsed"],
    }

    if github_output:
        with open(github_output, "a") as f:
            for key, value in outputs.items():
                f.write(f"{key}={value}\n")
    else:
        for key, value in outputs.items():
            print(f"{key}={value}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
