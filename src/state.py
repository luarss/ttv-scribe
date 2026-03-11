"""File-based state management for VOD tracking.

Replaces SQLite database with JSON files for simpler deployment.
"""
import enum
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

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
    """Record for a streamer being tracked"""
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
    """Manages VOD state via JSON files"""

    def __init__(self, state_dir: str | None = None):
        """Initialize state manager

        Args:
            state_dir: Directory for state files. Defaults to settings.state_file_dir
        """
        if state_dir is None:
            settings = get_settings()
            state_dir = settings.state_file_dir

        self.state_dir = Path(state_dir) if state_dir else Path("./state")
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.vods_file = self.state_dir / "vods.json"
        self.streamers_file = self.state_dir / "streamers.json"

    def _load_vods(self) -> dict[str, VodRecord]:
        """Load all VOD records from file

        Returns:
            Dictionary mapping vod_id to VodRecord
        """
        if not self.vods_file.exists():
            return {}

        try:
            with open(self.vods_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {vod_id: VodRecord.from_dict(v) for vod_id, v in data.items()}
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to load vods file: {e}")
            return {}

    def _save_vods(self, vods: dict[str, VodRecord]):
        """Save all VOD records to file atomically with file locking

        Args:
            vods: Dictionary mapping vod_id to VodRecord
        """
        lock_path = self.vods_file.with_suffix(".lock")
        lock = FileLock(str(lock_path), timeout=10)
        with lock:
            data = {vod_id: v.to_dict() for vod_id, v in vods.items()}
            temp_path = self.vods_file.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.rename(self.vods_file)

    def get_vod(self, vod_id: str) -> VodRecord | None:
        """Get a VOD record by ID

        Args:
            vod_id: The VOD ID to look up

        Returns:
            VodRecord if found, None otherwise
        """
        vods = self._load_vods()
        return vods.get(vod_id)

    def add_vod(self, vod: VodRecord):
        """Add a new VOD record

        Args:
            vod: The VOD record to add
        """
        vods = self._load_vods()
        vods[vod.vod_id] = vod
        self._save_vods(vods)
        logger.debug(f"Added VOD {vod.vod_id} to state")

    def update_vod(self, vod_id: str, **kwargs):
        """Update a VOD record

        Args:
            vod_id: The VOD ID to update
            **kwargs: Fields to update
        """
        vods = self._load_vods()
        if vod_id not in vods:
            logger.warning(f"VOD {vod_id} not found in state")
            return

        vod = vods[vod_id]
        for key, value in kwargs.items():
            if hasattr(vod, key):
                setattr(vod, key, value)
        vods[vod_id] = vod
        self._save_vods(vods)
        logger.debug(f"Updated VOD {vod_id}: {kwargs}")

    def get_vods_by_status(self, status: VodStatus | str) -> list[VodRecord]:
        """Get all VODs with a specific status

        Args:
            status: The status to filter by

        Returns:
            List of VodRecords with the given status
        """
        if isinstance(status, VodStatus):
            status = status.value

        vods = self._load_vods()
        return [v for v in vods.values() if v.status == status]

    def is_processed(self, vod_id: str) -> bool:
        """Check if a VOD has been processed (completed or failed)

        Args:
            vod_id: The VOD ID to check

        Returns:
            True if VOD is completed or failed
        """
        vod = self.get_vod(vod_id)
        if vod is None:
            return False
        return vod.status in (VodStatus.COMPLETED.value, VodStatus.FAILED.value)

    def get_pending_vods(self) -> list[VodRecord]:
        """Get all VODs awaiting download

        Returns:
            List of pending VodRecords
        """
        return self.get_vods_by_status(VodStatus.PENDING)

    def get_downloading_vods(self) -> list[VodRecord]:
        """Get all VODs currently being downloaded

        Returns:
            List of downloading VodRecords
        """
        return self.get_vods_by_status(VodStatus.DOWNLOADING)

    def get_transcribing_vods(self) -> list[VodRecord]:
        """Get all VODs currently being transcribed

        Returns:
            List of transcribing VodRecords
        """
        return self.get_vods_by_status(VodStatus.TRANSCRIBING)

    def get_completed_vods(self) -> list[VodRecord]:
        """Get all completed VODs

        Returns:
            List of completed VodRecords
        """
        return self.get_vods_by_status(VodStatus.COMPLETED)

    # Streamer management methods

    def _load_streamers(self) -> dict[str, StreamerRecord]:
        """Load all streamer records from file

        Returns:
            Dictionary mapping username to StreamerRecord
        """
        if not self.streamers_file.exists():
            return {}

        try:
            with open(self.streamers_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {username: StreamerRecord.from_dict(s) for username, s in data.items()}
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to load streamers file: {e}")
            return {}

    def _save_streamers(self, streamers: dict[str, StreamerRecord]):
        """Save all streamer records to file atomically with file locking

        Args:
            streamers: Dictionary mapping username to StreamerRecord
        """
        lock_path = self.streamers_file.with_suffix(".lock")
        lock = FileLock(str(lock_path), timeout=10)
        with lock:
            data = {username: s.to_dict() for username, s in streamers.items()}
            temp_path = self.streamers_file.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.rename(self.streamers_file)

    def get_streamers(self) -> list[StreamerRecord]:
        """Get all tracked streamers

        Returns:
            List of StreamerRecords
        """
        return list(self._load_streamers().values())

    def add_streamer(self, streamer: StreamerRecord):
        """Add a new streamer to track

        Args:
            streamer: The streamer record to add
        """
        streamers = self._load_streamers()
        streamers[streamer.username] = streamer
        self._save_streamers(streamers)
        logger.debug(f"Added streamer {streamer.username} to tracking")

    def get_streamer(self, username: str) -> StreamerRecord | None:
        """Get a streamer record by username

        Args:
            username: The streamer username

        Returns:
            StreamerRecord if found, None otherwise
        """
        streamers = self._load_streamers()
        return streamers.get(username)

    def update_streamer(self, username: str, **kwargs):
        """Update a streamer record

        Args:
            username: The streamer username to update
            **kwargs: Fields to update
        """
        streamers = self._load_streamers()
        if username not in streamers:
            logger.warning(f"Streamer {username} not found in state")
            return

        streamer = streamers[username]
        for key, value in kwargs.items():
            if hasattr(streamer, key):
                setattr(streamer, key, value)
        streamers[username] = streamer
        self._save_streamers(streamers)
        logger.debug(f"Updated streamer {username}: {kwargs}")

    def get_vods_by_streamer(self, username: str) -> list[VodRecord]:
        """Get all VODs for a specific streamer

        Args:
            username: The streamer username

        Returns:
            List of VodRecords for the streamer
        """
        vods = self._load_vods()
        return [v for v in vods.values() if v.streamer == username]

    def get_all_vods(self) -> list[VodRecord]:
        """Get all VOD records

        Returns:
            List of all VodRecords
        """
        return list(self._load_vods().values())


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