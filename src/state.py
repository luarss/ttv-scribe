"""File-based state management for VOD tracking.

Uses JSON files to persist VOD and streamer records.
- Streamers = subdirectories in transcripts/ (for discovery) + vods.json (for metadata)
- VODs = vods.json (for in-progress) + .txt files in transcripts/ (for completed)
"""

import enum
import fcntl
import json
import logging
import os
import threading
import time
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
    created_at: str = field(
        default_factory=lambda: (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
    )

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
    created_at: str = field(
        default_factory=lambda: (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VodRecord":
        return cls(**data)


class StateManager:
    """Manages VOD state using JSON files for persistence.

    - Completed VODs: inferred from transcripts directory (matching .txt files)
    - In-progress VODs: stored in vods.json
    - Streamers: stored in streamers.json (for metadata like twitch_id)
    """

    VODS_FILE = "vods.json"
    STREAMERS_FILE = "streamers.json"

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

        self.transcript_dir = (
            Path(transcript_dir) if transcript_dir else Path("./transcripts")
        )
        self.transcript_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache
        self._vods_cache: dict[str, VodRecord] = {}
        self._streamers_cache: dict[str, StreamerRecord] = {}
        self._load_state()

    def _load_state(self):
        """Load state from JSON files"""
        # Load vods
        vods_file = self.state_dir / self.VODS_FILE
        if vods_file.exists():
            try:
                with open(vods_file) as f:
                    data = json.load(f)
                    for vod_data in data.get("vods", []):
                        vod = VodRecord.from_dict(vod_data)
                        self._vods_cache[vod.vod_id] = vod
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load vods.json: {e}")

        # Load streamers
        streamers_file = self.state_dir / self.STREAMERS_FILE
        if streamers_file.exists():
            try:
                with open(streamers_file) as f:
                    data = json.load(f)
                    for streamer_data in data.get("streamers", []):
                        streamer = StreamerRecord.from_dict(streamer_data)
                        self._streamers_cache[streamer.username] = streamer
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load streamers.json: {e}")

    def _save_vods(self):
        """Save vods cache to JSON file with atomic write and file locking."""
        vods_file = self.state_dir / self.VODS_FILE
        temp_file = self.state_dir / f"{self.VODS_FILE}.tmp"
        data = {"vods": [vod.to_dict() for vod in self._vods_cache.values()]}

        # Write to temp file first (atomic write pattern)
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)

        # Lock the target file before rename to prevent concurrent writes
        lock_file = self.state_dir / f"{self.VODS_FILE}.lock"
        with open(lock_file, "w") as lockf:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
            try:
                os.replace(temp_file, vods_file)  # Atomic on POSIX
            finally:
                fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)

        # Clean up lock file (optional, safe to leave)
        try:
            lock_file.unlink()
        except OSError:
            pass

    def _save_streamers(self):
        """Save streamers cache to JSON file with atomic write and file locking."""
        streamers_file = self.state_dir / self.STREAMERS_FILE
        temp_file = self.state_dir / f"{self.STREAMERS_FILE}.tmp"
        data = {"streamers": [s.to_dict() for s in self._streamers_cache.values()]}

        # Write to temp file first (atomic write pattern)
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)

        # Lock the target file before rename to prevent concurrent writes
        lock_file = self.state_dir / f"{self.STREAMERS_FILE}.lock"
        with open(lock_file, "w") as lockf:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
            try:
                os.replace(temp_file, streamers_file)  # Atomic on POSIX
            finally:
                fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)

        # Clean up lock file (optional, safe to leave)
        try:
            lock_file.unlink()
        except OSError:
            pass

    def _scan_completed_vods(self) -> dict[str, VodRecord]:
        """Scan transcripts directory for completed VODs.

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
                # Don't override if already in cache with more info
                if vod_id not in self._vods_cache:
                    vods[vod_id] = VodRecord(
                        vod_id=vod_id,
                        streamer=username,
                        status=VodStatus.COMPLETED.value,
                        transcript_path=str(transcript_file),
                    )

        return vods

    def _get_all_vods(self) -> dict[str, VodRecord]:
        """Get all VODs (from cache + completed from filesystem)"""
        # Start with cached vods
        all_vods = dict(self._vods_cache)
        # Add completed vods from filesystem that aren't in cache
        for vod_id, vod in self._scan_completed_vods().items():
            if vod_id not in all_vods:
                all_vods[vod_id] = vod
        return all_vods

    def get_vod(self, vod_id: str) -> VodRecord | None:
        """Get a VOD record by ID

        Args:
            vod_id: The VOD ID to look up

        Returns:
            VodRecord if found, None otherwise
        """
        all_vods = self._get_all_vods()
        return all_vods.get(vod_id)

    def add_vod(self, vod: VodRecord):
        """Add a VOD to the state and create transcript directory

        Args:
            vod: The VOD record to add
        """
        # Create directory
        streamer_dir = self.transcript_dir / vod.streamer
        streamer_dir.mkdir(parents=True, exist_ok=True)

        # Add to cache and persist
        self._vods_cache[vod.vod_id] = vod
        self._save_vods()
        logger.debug(f"Added VOD {vod.vod_id} to state")

    def update_vod(self, vod_id: str, **kwargs):
        """Update a VOD record

        Args:
            vod_id: The VOD ID to update
            **kwargs: Fields to update
        """
        if vod_id not in self._vods_cache:
            logger.warning(f"Attempted to update unknown VOD {vod_id}")
            return

        vod = self._vods_cache[vod_id]
        for key, value in kwargs.items():
            if hasattr(vod, key):
                setattr(vod, key, value)

        self._save_vods()
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

        all_vods = self._get_all_vods()
        return [v for v in all_vods.values() if v.status == status]

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
            List of completed VodRecords (all VODs with transcripts)
        """
        return self.get_vods_by_status(VodStatus.COMPLETED)

    # Streamer management methods

    def _get_all_streamers(self) -> dict[str, StreamerRecord]:
        """Get all streamers (from cache + discovered from filesystem)

        Returns:
            Dictionary mapping username to StreamerRecord
        """
        # Start with cached streamers
        all_streamers = dict(self._streamers_cache)

        if not self.transcript_dir.exists():
            return all_streamers

        # Add discovered streamers that aren't in cache
        for streamer_dir in self.transcript_dir.iterdir():
            if not streamer_dir.is_dir():
                continue
            username = streamer_dir.name
            if username not in all_streamers:
                all_streamers[username] = StreamerRecord(username=username)

        return all_streamers

    def get_streamers(self) -> list[StreamerRecord]:
        """Get all tracked streamers

        Returns:
            List of StreamerRecords
        """
        return list(self._get_all_streamers().values())

    def add_streamer(self, streamer: StreamerRecord):
        """Add a new streamer (creates directory in transcripts and persists)

        Args:
            streamer: The streamer record to add
        """
        # Create directory
        streamer_dir = self.transcript_dir / streamer.username
        streamer_dir.mkdir(parents=True, exist_ok=True)

        # Add to cache and persist
        self._streamers_cache[streamer.username] = streamer
        self._save_streamers()
        logger.debug(f"Added streamer {streamer.username} to state")

    def get_streamer(self, username: str) -> StreamerRecord | None:
        """Get a streamer record by username

        Args:
            username: The streamer username

        Returns:
            StreamerRecord if found, None otherwise
        """
        all_streamers = self._get_all_streamers()
        return all_streamers.get(username)

    def update_streamer(self, username: str, **kwargs):
        """Update a streamer record

        Args:
            username: The streamer username to update
            **kwargs: Fields to update (e.g., twitch_id)
        """
        # Get or create streamer
        if username in self._streamers_cache:
            streamer = self._streamers_cache[username]
        else:
            # Create new from filesystem discovery
            streamer = StreamerRecord(username=username)
            self._streamers_cache[username] = streamer

        # Update fields
        for key, value in kwargs.items():
            if hasattr(streamer, key):
                setattr(streamer, key, value)

        self._save_streamers()
        logger.debug(f"Updated streamer {username}: {kwargs}")

    def get_vods_by_streamer(self, username: str) -> list[VodRecord]:
        """Get all VODs for a specific streamer

        Args:
            username: The streamer username

        Returns:
            List of VodRecords for the streamer
        """
        all_vods = self._get_all_vods()
        return [v for v in all_vods.values() if v.streamer == username]

    def get_all_vods(self) -> list[VodRecord]:
        """Get all VOD records

        Returns:
            List of all VodRecords
        """
        return list(self._get_all_vods().values())


# Global state manager instance with thread-safe caching
import threading

_state_manager: StateManager | None = None
_state_manager_lock = threading.Lock()
_state_manager_timestamp: float = 0
STATE_CACHE_TTL_SECONDS = 60  # Refresh cache after 60 seconds


def get_state_manager() -> StateManager:
    """Get the global state manager instance with TTL-based cache refresh.

    Thread-safe singleton that refreshes the cache after TTL expires.
    This avoids redundant file reads while ensuring state stays fresh.

    Returns:
        The StateManager instance
    """
    global _state_manager, _state_manager_timestamp

    current_time = time.time()

    with _state_manager_lock:
        if _state_manager is None or (current_time - _state_manager_timestamp) > STATE_CACHE_TTL_SECONDS:
            _state_manager = StateManager()
            _state_manager_timestamp = current_time
        return _state_manager


def reset_state_manager():
    """Reset the state manager singleton (useful for testing or forced refresh)."""
    global _state_manager, _state_manager_timestamp
    with _state_manager_lock:
        _state_manager = None
        _state_manager_timestamp = 0


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
