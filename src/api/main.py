"""FastAPI application for TTV-Scribe"""
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..config import get_settings
from ..state import (
    StateManager,
    get_state_manager,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="TTV-Scribe API",
    description="Twitch Transcript Intelligence Database",
    version="0.1.0",
)

# Add CORS middleware to allow frontend to access API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_state() -> StateManager:
    """Get state manager instance"""
    return get_state_manager()


# Pydantic models for API
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


# API Endpoints

@app.get("/")
def root():
    """Health check endpoint"""
    return {"status": "ok", "version": "0.1.0"}


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
