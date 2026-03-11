"""Full-text search for transcripts"""
import json
import logging
import os
from pathlib import Path
from typing import List

from .config import get_settings

logger = logging.getLogger(__name__)


def search_transcripts(
    query: str,
    limit: int = 20,
    transcript_dir: str | None = None,
) -> List[dict]:
    """Search transcripts using simple text matching

    Args:
        query: Search query string
        limit: Maximum number of results
        transcript_dir: Base directory for transcripts. Defaults to settings.transcript_dir

    Returns:
        List of matching transcripts with metadata
    """
    if transcript_dir is None:
        settings = get_settings()
        transcript_dir = settings.transcript_dir

    transcript_path = Path(transcript_dir)
    if not transcript_path.exists():
        logger.warning(f"Transcript directory does not exist: {transcript_dir}")
        return []

    matches = []
    query_lower = query.lower()

    # Walk through all transcript JSON files
    for json_file in transcript_path.rglob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                transcript_data = json.load(f)

            text = transcript_data.get("text", "")
            if not text:
                continue

            # Simple case-insensitive search
            if query_lower in text.lower():
                # Calculate position for relevance
                pos = text.lower().find(query_lower)
                context_start = max(0, pos - 100)
                context_end = min(len(text), pos + len(query) + 100)

                matches.append({
                    "transcript_file": str(json_file),
                    "vod_id": transcript_data.get("vod_id"),
                    "vod_title": transcript_data.get("title"),
                    "streamer": transcript_data.get("streamer"),
                    "recorded_at": transcript_data.get("recorded_at"),
                    "text_preview": text[context_start:context_end],
                    "match_position": pos,
                })

        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to read {json_file}: {e}")
            continue

    # Sort by match position (earlier matches first)
    matches.sort(key=lambda x: x.get("match_position", 0))

    return matches[:limit]


if __name__ == "__main__":
    # Test search
    logging.basicConfig(level=logging.INFO)
    results = search_transcripts("test query")
    for r in results:
        print(f"{r['streamer']}: {r['vod_title'][:50]} - {r['text_preview'][:50]}")