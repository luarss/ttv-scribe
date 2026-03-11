"""FastAPI application for TTV-Scribe"""
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..state import (
    StateManager,
    VodRecord,
    StreamerRecord,
    get_state_manager,
)
from ..search import search_transcripts

logger = logging.getLogger(__name__)

app = FastAPI(
    title="TTV-Scribe API",
    description="Twitch Transcript Intelligence Database",
    version="0.1.0",
)


def get_state() -> StateManager:
    """Get state manager instance"""
    return get_state_manager()


# Pydantic models for API
class StreamerCreate(BaseModel):
    username: str
    twitch_id: Optional[str] = None


class StreamerResponse(BaseModel):
    username: str
    twitch_id: Optional[str]
    created_at: str


class VodResponse(BaseModel):
    vod_id: str
    streamer: str
    title: Optional[str]
    duration: Optional[int]
    recorded_at: Optional[str]
    status: str
    transcript_path: Optional[str]
    created_at: str


class TranscriptResponse(BaseModel):
    vod_id: str
    streamer: str
    title: Optional[str]
    text: str
    transcript_metadata: Optional[dict]
    recorded_at: Optional[str]


class SearchResult(BaseModel):
    transcript_file: str
    vod_id: Optional[str]
    vod_title: Optional[str]
    streamer: Optional[str]
    recorded_at: Optional[str]
    text_preview: str
    match_position: int


# API Endpoints

@app.get("/")
def root():
    """Health check endpoint"""
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/streamers", response_model=list[StreamerResponse])
def list_streamers():
    """List all tracked streamers"""
    state = get_state()
    streamers = state.get_streamers()
    return [
        StreamerResponse(
            username=s.username,
            twitch_id=s.twitch_id,
            created_at=s.created_at,
        )
        for s in streamers
    ]


@app.post("/api/streamers", response_model=StreamerResponse)
def add_streamer(streamer: StreamerCreate):
    """Add a new streamer to track"""
    state = get_state()

    # Check if already exists
    existing = state.get_streamer(streamer.username)
    if existing:
        raise HTTPException(status_code=400, detail="Streamer already tracked")

    new_streamer = StreamerRecord(
        username=streamer.username,
        twitch_id=streamer.twitch_id,
    )
    state.add_streamer(new_streamer)

    return StreamerResponse(
        username=new_streamer.username,
        twitch_id=new_streamer.twitch_id,
        created_at=new_streamer.created_at,
    )


@app.get("/api/streamers/{username}/recent", response_model=list[VodResponse])
def get_streamer_recent_vods(username: str, limit: int = 10):
    """Get recent VODs for a streamer"""
    state = get_state()
    vods = state.get_vods_by_streamer(username)

    # Sort by recorded_at descending
    vods.sort(key=lambda v: v.recorded_at or "", reverse=True)

    # Apply limit
    vods = vods[:limit]

    return [
        VodResponse(
            vod_id=v.vod_id,
            streamer=v.streamer,
            title=v.title,
            duration=v.duration,
            recorded_at=v.recorded_at,
            status=v.status,
            transcript_path=v.transcript_path,
            created_at=v.created_at,
        )
        for v in vods
    ]


@app.get("/api/vods", response_model=list[VodResponse])
def list_vods(
    streamer: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
):
    """List all VODs, optionally filtered by streamer or status"""
    state = get_state()

    if streamer:
        vods = state.get_vods_by_streamer(streamer)
    elif status:
        try:
            vods = state.get_vods_by_status(status)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid status")
    else:
        vods = state.get_all_vods()

    # Apply limit
    vods = vods[:limit]

    return [
        VodResponse(
            vod_id=v.vod_id,
            streamer=v.streamer,
            title=v.title,
            duration=v.duration,
            recorded_at=v.recorded_at,
            status=v.status,
            transcript_path=v.transcript_path,
            created_at=v.created_at,
        )
        for v in vods
    ]


@app.get("/api/vods/{vod_id}/transcript", response_model=TranscriptResponse)
def get_vod_transcript(vod_id: str):
    """Get transcript for a specific VOD from the transcript file"""
    state = get_state()
    settings = get_settings()

    # Get VOD record to find the transcript path
    vod = state.get_vod(vod_id)
    if not vod:
        raise HTTPException(status_code=404, detail="VOD not found")

    # Determine transcript file path
    if vod.transcript_path:
        transcript_file = Path(vod.transcript_path)
    else:
        # Default path: {transcript_dir}/{vod_id}.json
        transcript_file = Path(settings.transcript_dir) / f"{vod_id}.json"

    if not transcript_file.exists():
        raise HTTPException(status_code=404, detail="Transcript not found")

    try:
        with open(transcript_file, "r", encoding="utf-8") as f:
            transcript_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to read transcript file: {e}")
        raise HTTPException(status_code=500, detail="Failed to read transcript")

    return TranscriptResponse(
        vod_id=transcript_data.get("vod_id", vod_id),
        streamer=transcript_data.get("streamer", vod.streamer),
        title=transcript_data.get("title", vod.title),
        text=transcript_data.get("text", ""),
        transcript_metadata=transcript_data.get("transcript_metadata"),
        recorded_at=transcript_data.get("recorded_at", vod.recorded_at),
    )


@app.get("/api/search", response_model=list[SearchResult])
def search(q: str, limit: int = 20):
    """Search transcripts by keyword"""
    if not q or len(q) < 2:
        return []

    results = search_transcripts(query=q, limit=limit)
    return results


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)