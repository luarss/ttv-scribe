"""FastAPI application for TTV-Scribe"""
import logging
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db, init_db
from ..models import Streamer, Vod, Transcript
from ..search import search_transcripts

logger = logging.getLogger(__name__)

app = FastAPI(
    title="TTV-Scribe API",
    description="Twitch Transcript Intelligence Database",
    version="0.1.0",
)


# Initialize database on startup
@app.on_event("startup")
def startup():
    try:
        init_db()
    except Exception as e:
        logger.warning(f"Could not initialize database: {e}")


# Pydantic models for API
class StreamerCreate(BaseModel):
    username: str


class StreamerResponse(BaseModel):
    id: int
    username: str
    twitch_id: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class VodResponse(BaseModel):
    id: int
    vod_id: str
    streamer_id: int
    title: Optional[str]
    duration: Optional[int]
    recorded_at: Optional[datetime]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class TranscriptResponse(BaseModel):
    id: int
    vod_id: int
    text: str
    transcript_metadata: Optional[dict]
    cost: Optional[float]
    created_at: datetime

    class Config:
        from_attributes = True


class SearchResult(BaseModel):
    transcript_id: int
    vod_id: str
    vod_title: Optional[str]
    streamer: str
    recorded_at: Optional[str]
    text_preview: str
    rank: float


# API Endpoints

@app.get("/")
def root():
    """Health check endpoint"""
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/streamers", response_model=list[StreamerResponse])
def list_streamers(db: Session = Depends(get_db)):
    """List all tracked streamers"""
    return db.query(Streamer).order_by(Streamer.created_at.desc()).all()


@app.post("/api/streamers", response_model=StreamerResponse)
def add_streamer(streamer: StreamerCreate, db: Session = Depends(get_db)):
    """Add a new streamer to track"""
    # Check if already exists
    existing = db.query(Streamer).filter(Streamer.username == streamer.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Streamer already tracked")

    new_streamer = Streamer(username=streamer.username)
    db.add(new_streamer)
    db.commit()
    db.refresh(new_streamer)

    return new_streamer


@app.get("/api/streamers/{streamer_id}/recent", response_model=list[VodResponse])
def get_streamer_recent_vods(streamer_id: int, limit: int = 10, db: Session = Depends(get_db)):
    """Get recent VODs for a streamer"""
    vods = (
        db.query(Vod)
        .filter(Vod.streamer_id == streamer_id)
        .order_by(Vod.recorded_at.desc())
        .limit(limit)
        .all()
    )
    return vods


@app.get("/api/vods/{vod_id}/transcript", response_model=TranscriptResponse)
def get_vod_transcript(vod_id: str, db: Session = Depends(get_db)):
    """Get transcript for a specific VOD"""
    vod = db.query(Vod).filter(Vod.vod_id == vod_id).first()
    if not vod:
        raise HTTPException(status_code=404, detail="VOD not found")

    transcript = db.query(Transcript).filter(Transcript.vod_id == vod.id).first()
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")

    return transcript


@app.get("/api/search", response_model=list[SearchResult])
def search(q: str, limit: int = 20, db: Session = Depends(get_db)):
    """Search transcripts by keyword"""
    if not q or len(q) < 2:
        return []

    results = search_transcripts(query=q, limit=limit, session=db)
    return results


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)