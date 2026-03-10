"""Database models for TTV-Scribe"""
import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Text, JSON, Float, Index
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class VodStatus(str, enum.Enum):
    """Status of a VOD in the pipeline"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    COMPLETED = "completed"
    FAILED = "failed"


class Streamer(Base):
    """Twitch streamer being tracked"""
    __tablename__ = "streamers"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    twitch_id = Column(String(50), unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationship to VODs
    vods = relationship("Vod", back_populates="streamer", cascade="all, delete-orphan")


class Vod(Base):
    """Twitch VOD"""
    __tablename__ = "vods"

    id = Column(Integer, primary_key=True)
    vod_id = Column(String(50), unique=True, nullable=False, index=True)
    streamer_id = Column(Integer, ForeignKey("streamers.id"), nullable=False)
    title = Column(String(500), nullable=True)
    duration = Column(Integer, nullable=True)  # Duration in seconds
    recorded_at = Column(DateTime, nullable=True)
    status = Column(Enum(VodStatus), default=VodStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    streamer = relationship("Streamer", back_populates="vods")
    transcript = relationship("Transcript", back_populates="vod", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_vod_status", "status"),
        Index("idx_vod_streamer_status", "streamer_id", "status"),
    )


class Transcript(Base):
    """Transcript for a VOD"""
    __tablename__ = "transcripts"

    id = Column(Integer, primary_key=True)
    vod_id = Column(Integer, ForeignKey("vods.id"), nullable=False, unique=True)
    text = Column(Text, nullable=False)
    transcript_metadata = Column(JSON, nullable=True)  # Stores timestamp key moments, etc.
    cost = Column(Float, nullable=True)  # Transcription cost in USD
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationship
    vod = relationship("Vod", back_populates="transcript")

    __table_args__ = (
        Index("idx_transcript_vod", "vod_id"),
    )