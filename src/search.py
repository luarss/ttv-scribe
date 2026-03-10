"""Full-text search for transcripts"""
import logging
from typing import List, Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .database import get_db_session
from .models import Transcript, Vod, Streamer

logger = logging.getLogger(__name__)


def search_transcripts(
    query: str,
    limit: int = 20,
    session: Optional[Session] = None
) -> List[dict]:
    """Search transcripts using PostgreSQL full-text search

    Args:
        query: Search query string
        limit: Maximum number of results
        session: Optional database session

    Returns:
        List of matching transcripts with metadata
    """
    close_session = False
    if session is None:
        session = get_db_session().__enter__()
        close_session = True

    try:
        # Use pg_trgm for fuzzy search if available
        # Fall back to ILIKE for simple matching
        results = (
            session.query(
                Transcript,
                Vod,
                Streamer,
                func.similarity(Transcript.text, query).label("rank")
            )
            .join(Vod, Transcript.vod_id == Vod.id)
            .join(Streamer, Vod.streamer_id == Streamer.id)
            .filter(Transcript.text.ilike(f"%{query}%"))
            .order_by(text("rank DESC"))
            .limit(limit)
            .all()
        )

        matches = []
        for transcript, vod, streamer, rank in results:
            matches.append({
                "transcript_id": transcript.id,
                "vod_id": vod.vod_id,
                "vod_title": vod.title,
                "streamer": streamer.username,
                "recorded_at": vod.recorded_at.isoformat() if vod.recorded_at else None,
                "text_preview": transcript.text[:200] + "..." if len(transcript.text) > 200 else transcript.text,
                "rank": float(rank) if rank else 0.0,
            })

        return matches

    finally:
        if close_session:
            session.close()


def enable_pg_trgm(session: Session):
    """Enable pg_trgm extension for fuzzy search"""
    try:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        session.commit()
    except Exception as e:
        logger.warning(f"Could not enable pg_trgm: {e}")


if __name__ == "__main__":
    # Test search
    logging.basicConfig(level=logging.INFO)
    results = search_transcripts("test query")
    for r in results:
        print(f"{r['streamer']}: {r['vod_title'][:50]} - {r['text_preview'][:50]}")