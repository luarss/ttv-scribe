"""File-based state management for VOD tracking.

Replaces SQLite database with file-based inference.
Streamers and VODs are inferred from the transcripts directory structure.
- Streamers = subdirectories in transcripts/
- VODs = .txt files within each streamer's directory
"""
import enum
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_settings

logger = logging.getLogger(__name__)


class VodStatus(str, enum.Enum):
    """Status of a VOD in the pipeline"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StreamerRecord:
    """Record for a streamer being tracked (inferred from transcripts directory)"""
    username: str
    twitch_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StreamerRecord":
        return cls(**data)


@dataclass
class VodRecord:
    """Record for a VOD in the state file"""
    vod_id: str
    streamer: str
    title: str | None = None
    duration: int | None = None  # Duration in seconds
    recorded_at: str | None = None  # ISO format datetime string
    status: str = VodStatus.PENDING.value
    transcript_path: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VodRecord":
        return cls(**data)


class StateManager:
    """Manages VOD state by inferring from transcripts directory.

    - Streamers = subdirectories in transcripts/
    - VODs = transcript files within each streamer's directory
    """

    def __init__(self, state_dir: str | None = None, transcript_dir: str | None = None):
        """Initialize state manager

        Args:
            state_dir: Directory for state files. Defaults to settings.state_file_dir
            transcript_dir: Directory for transcripts. Defaults to settings.transcript_dir
        """
        if state_dir is None:
            settings = get_settings()
            state_dir = settings.state_file_dir

        if transcript_dir is None:
            settings = get_settings()
            transcript_dir = settings.transcript_dir

        self.state_dir = Path(state_dir) if state_dir else Path("./state")
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.transcript_dir = Path(transcript_dir) if transcript_dir else Path("./transcripts")
        self.transcript_dir.mkdir(parents=True, exist_ok=True)

    def _scan_vods(self) -> dict[str, VodRecord]:
        """Scan transcripts directory for VODs.

        Returns:
            Dictionary mapping vod_id to VodRecord
        """
        vods: dict[str, VodRecord] = {}

        if not self.transcript_dir.exists():
            return vods

        for streamer_dir in self.transcript_dir.iterdir():
            if not streamer_dir.is_dir():
                continue

            username = streamer_dir.name

            for transcript_file in streamer_dir.glob("*.txt"):
                vod_id = transcript_file.stem  # filename without extension
                vods[vod_id] = VodRecord(
                    vod_id=vod_id,
                    streamer=username,
                    status=VodStatus.COMPLETED.value,
                    transcript_path=str(transcript_file),
                )

        return vods

    def get_vod(self, vod_id: str) -> VodRecord | None:
        """Get a VOD record by ID

        Args:
            vod_id: The VOD ID to look up

        Returns:
            VodRecord if found, None otherwise
        """
        vods = self._scan_vods()
        return vods.get(vod_id)

    def add_vod(self, vod: VodRecord):
        """Create a transcript directory for a VOD

        Args:
            vod: The VOD record to add
        """
        streamer_dir = self.transcript_dir / vod.streamer
        streamer_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Created directory for VOD {vod.vod_id} at {streamer_dir}")

    def update_vod(self, vod_id: str, **kwargs):
        """Update a VOD record (no-op, VODs are inferred from filesystem)

        Args:
            vod_id: The VOD ID to update
            **kwargs: Fields to update (ignored)
        """
        pass

    def get_vods_by_status(self, status: VodStatus | str) -> list[VodRecord]:
        """Get all VODs with a specific status

        Args:
            status: The status to filter by

        Returns:
            List of VodRecords with the given status
        """
        if status == VodStatus.PENDING.value or status == VodStatus.PENDING:
            return []
        if status == VodStatus.DOWNLOADING.value or status == VodStatus.DOWNLOADING:
            return []
        if status == VodStatus.TRANSCRIBING.value or status == VodStatus.TRANSCRIBING:
            return []

        vods = self._scan_vods()
        if isinstance(status, VodStatus):
            status = status.value
        return [v for v in vods.values() if v.status == status]

    def is_processed(self, vod_id: str) -> bool:
        """Check if a VOD has been processed (completed)

        Args:
            vod_id: The VOD ID to check

        Returns:
            True if VOD has a transcript file
        """
        vod = self.get_vod(vod_id)
        if vod is None:
            return False
        return vod.status == VodStatus.COMPLETED.value

    def get_pending_vods(self) -> list[VodRecord]:
        """Get all VODs awaiting download

        Returns:
            Empty list (VODs are inferred, not tracked)
        """
        return []

    def get_downloading_vods(self) -> list[VodRecord]:
        """Get all VODs currently being downloaded

        Returns:
            Empty list (VODs are inferred, not tracked)
        """
        return []

    def get_transcribing_vods(self) -> list[VodRecord]:
        """Get all VODs currently being transcribed

        Returns:
            Empty list (VODs are inferred, not tracked)
        """
        return []

    def get_completed_vods(self) -> list[VodRecord]:
        """Get all completed VODs

        Returns:
            List of completed VodRecords (all VODs with transcripts)
        """
        return self.get_vods_by_status(VodStatus.COMPLETED)

    # Streamer management methods

    def _scan_streamers(self) -> dict[str, StreamerRecord]:
        """Scan transcripts directory for streamers.

        Returns:
            Dictionary mapping username to StreamerRecord
        """
        streamers: dict[str, StreamerRecord] = {}

        if not self.transcript_dir.exists():
            return streamers

        for streamer_dir in self.transcript_dir.iterdir():
            if not streamer_dir.is_dir():
                continue

            streamers[streamer_dir.name] = StreamerRecord(
                username=streamer_dir.name,
            )

        return streamers

    def get_streamers(self) -> list[StreamerRecord]:
        """Get all tracked streamers

        Returns:
            List of StreamerRecords
        """
        return list(self._scan_streamers().values())

    def add_streamer(self, streamer: StreamerRecord):
        """Add a new streamer (creates directory in transcripts)

        Args:
            streamer: The streamer record to add
        """
        streamer_dir = self.transcript_dir / streamer.username
        streamer_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Created directory for streamer {streamer.username}")

    def get_streamer(self, username: str) -> StreamerRecord | None:
        """Get a streamer record by username

        Args:
            username: The streamer username

        Returns:
            StreamerRecord if found, None otherwise
        """
        streamers = self._scan_streamers()
        return streamers.get(username)

    def update_streamer(self, username: str, **kwargs):
        """Update a streamer record (no-op, streamers are inferred)

        Args:
            username: The streamer username to update
            **kwargs: Fields to update (ignored)
        """
        pass

    def get_vods_by_streamer(self, username: str) -> list[VodRecord]:
        """Get all VODs for a specific streamer

        Args:
            username: The streamer username

        Returns:
            List of VodRecords for the streamer
        """
        vods = self._scan_vods()
        return [v for v in vods.values() if v.streamer == username]

    def get_all_vods(self) -> list[VodRecord]:
        """Get all VOD records

        Returns:
            List of all VodRecords
        """
        return list(self._scan_vods().values())


# Global state manager instance
_state_manager: StateManager | None = None


def get_state_manager() -> StateManager:
    """Get the global state manager instance

    Returns:
        The StateManager instance
    """
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager


# Convenience functions that use the global state manager
def load_processed_vods() -> set[str]:
    """Load set of processed VOD IDs from file

    Returns:
        Set of processed VOD IDs (completed or failed)
    """
    manager = get_state_manager()
    completed = manager.get_completed_vods()
    # Also include failed vods
    failed = manager.get_vods_by_status(VodStatus.FAILED)
    return {v.vod_id for v in completed + failed}


def get_vod_status(vod_id: str) -> VodStatus | None:
    """Check status of a VOD

    Args:
        vod_id: The VOD ID to check

    Returns:
        VodStatus if found, None otherwise
    """
    manager = get_state_manager()
    vod = manager.get_vod(vod_id)
    if vod is None:
        return None
    return VodStatus(vod.status)


def set_vod_status(vod_id: str, status: VodStatus):
    """Update VOD status

    Args:
        vod_id: The VOD ID to update
        status: The new status
    """
    manager = get_state_manager()
    manager.update_vod(vod_id, status=status.value)


def get_pending_vods() -> list[dict[str, Any]]:
    """Get list of VODs awaiting download

    Returns:
        List of pending VOD records as dicts
    """
    manager = get_state_manager()
    vods = manager.get_pending_vods()
    return [v.to_dict() for v in vods]


def get_transcribing_vods() -> list[dict[str, Any]]:
    """Get list of VODs being transcribed

    Returns:
        List of transcribing VOD records as dicts
    """
    manager = get_state_manager()
    vods = manager.get_transcribing_vods()
    return [v.to_dict() for v in vods]


def get_downloading_vods() -> list[dict[str, Any]]:
    """Get list of VODs being downloaded

    Returns:
        List of downloading VOD records as dicts
    """
    manager = get_state_manager()
    vods = manager.get_downloading_vods()
    return [v.to_dict() for v in vods]


# Streamer convenience functions

def get_streamers() -> list[dict[str, Any]]:
    """Get all tracked streamers

    Returns:
        List of streamer records as dicts
    """
    manager = get_state_manager()
    streamers = manager.get_streamers()
    return [s.to_dict() for s in streamers]


def add_streamer(username: str, twitch_id: str | None = None):
    """Add a new streamer to track

    Args:
        username: The streamer's username
        twitch_id: Optional Twitch user ID
    """
    manager = get_state_manager()
    streamer = StreamerRecord(username=username, twitch_id=twitch_id)
    manager.add_streamer(streamer)


def get_streamer(username: str) -> dict[str, Any] | None:
    """Get a streamer by username

    Args:
        username: The streamer username

    Returns:
        Streamer record as dict if found, None otherwise
    """
    manager = get_state_manager()
    streamer = manager.get_streamer(username)
    return streamer.to_dict() if streamer else None


def update_streamer(username: str, **kwargs):
    """Update a streamer record

    Args:
        username: The streamer username to update
        **kwargs: Fields to update (e.g., twitch_id)
    """
    manager = get_state_manager()
    manager.update_streamer(username, **kwargs)