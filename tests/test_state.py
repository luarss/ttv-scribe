"""Tests for state management"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.state import (
    VodStatus,
    StreamerRecord,
    VodRecord,
    StateManager,
    get_state_manager,
    load_processed_vods,
    get_vod_status,
    set_vod_status,
    get_pending_vods,
    get_transcribing_vods,
    get_downloading_vods,
    get_streamers,
    add_streamer,
    get_streamer,
    update_streamer,
)


class TestVodStatus:
    """Tests for VodStatus enum"""

    def test_enum_values(self):
        """Test that all expected status values exist"""
        assert VodStatus.PENDING.value == "pending"
        assert VodStatus.DOWNLOADING.value == "downloading"
        assert VodStatus.TRANSCRIBING.value == "transcribing"
        assert VodStatus.COMPLETED.value == "completed"
        assert VodStatus.FAILED.value == "failed"

    def test_enum_is_string(self):
        """Test that VodStatus inherits from str"""
        assert isinstance(VodStatus.PENDING, str)
        assert VodStatus.PENDING == "pending"

    def test_enum_from_string(self):
        """Test creating enum from string value"""
        status = VodStatus("pending")
        assert status == VodStatus.PENDING


class TestStreamerRecord:
    """Tests for StreamerRecord dataclass"""

    def test_create_with_username(self):
        """Test creating a streamer record with just username"""
        streamer = StreamerRecord(username="testuser")
        assert streamer.username == "testuser"
        assert streamer.twitch_id is None
        assert streamer.created_at is not None

    def test_create_with_all_fields(self):
        """Test creating a streamer record with all fields"""
        streamer = StreamerRecord(
            username="testuser",
            twitch_id="123456",
            created_at="2024-01-15T12:00:00Z"
        )
        assert streamer.username == "testuser"
        assert streamer.twitch_id == "123456"
        assert streamer.created_at == "2024-01-15T12:00:00Z"

    def test_to_dict(self):
        """Test converting streamer record to dict"""
        streamer = StreamerRecord(username="testuser", twitch_id="123456")
        data = streamer.to_dict()
        assert data["username"] == "testuser"
        assert data["twitch_id"] == "123456"
        assert "created_at" in data

    def test_from_dict(self):
        """Test creating streamer record from dict"""
        data = {"username": "testuser", "twitch_id": "123456", "created_at": "2024-01-15T12:00:00Z"}
        streamer = StreamerRecord.from_dict(data)
        assert streamer.username == "testuser"
        assert streamer.twitch_id == "123456"


class TestVodRecord:
    """Tests for VodRecord dataclass"""

    def test_create_with_required_fields(self):
        """Test creating a VOD record with required fields"""
        vod = VodRecord(vod_id="123", streamer="testuser")
        assert vod.vod_id == "123"
        assert vod.streamer == "testuser"
        assert vod.status == VodStatus.PENDING.value
        assert vod.title is None
        assert vod.duration is None

    def test_create_with_all_fields(self):
        """Test creating a VOD record with all fields"""
        vod = VodRecord(
            vod_id="123",
            streamer="testuser",
            title="Test Stream",
            duration=3600,
            recorded_at="2024-01-15T12:00:00Z",
            status=VodStatus.COMPLETED.value,
            transcript_path="/path/to/transcript.txt",
        )
        assert vod.vod_id == "123"
        assert vod.streamer == "testuser"
        assert vod.title == "Test Stream"
        assert vod.duration == 3600
        assert vod.status == "completed"

    def test_to_dict(self):
        """Test converting VOD record to dict"""
        vod = VodRecord(vod_id="123", streamer="testuser", title="Test")
        data = vod.to_dict()
        assert data["vod_id"] == "123"
        assert data["streamer"] == "testuser"
        assert data["title"] == "Test"
        assert "created_at" in data

    def test_from_dict(self):
        """Test creating VOD record from dict"""
        data = {
            "vod_id": "123",
            "streamer": "testuser",
            "title": "Test",
            "duration": 3600,
            "status": "completed",
            "created_at": "2024-01-15T12:00:00Z",
        }
        vod = VodRecord.from_dict(data)
        assert vod.vod_id == "123"
        assert vod.streamer == "testuser"
        assert vod.title == "Test"


class TestStateManagerInit:
    """Tests for StateManager initialization"""

    def test_init_creates_directories(self, temp_dir):
        """Test that StateManager creates state and transcript directories"""
        state_dir = Path(temp_dir) / "state"
        transcript_dir = Path(temp_dir) / "transcripts"

        StateManager(state_dir=str(state_dir), transcript_dir=str(transcript_dir))

        assert state_dir.exists()
        assert transcript_dir.exists()

    def test_init_loads_existing_vods(self, temp_dir):
        """Test that StateManager loads existing VODs from file"""
        state_dir = Path(temp_dir)
        vods_file = state_dir / "vods.json"
        vods_file.write_text(json.dumps({
            "vods": [{"vod_id": "123", "streamer": "testuser", "created_at": "2024-01-15T12:00:00Z"}]
        }))

        manager = StateManager(state_dir=str(state_dir), transcript_dir=str(temp_dir))

        assert "123" in manager._vods_cache

    def test_init_handles_missing_vods_file(self, temp_dir):
        """Test that StateManager handles missing vods.json gracefully"""
        manager = StateManager(state_dir=str(temp_dir), transcript_dir=str(temp_dir))
        assert manager._vods_cache == {}

    def test_init_handles_corrupt_vods_file(self, temp_dir, caplog):
        """Test that StateManager handles corrupt JSON gracefully"""
        state_dir = Path(temp_dir)
        vods_file = state_dir / "vods.json"
        vods_file.write_text("not valid json")

        manager = StateManager(state_dir=str(state_dir), transcript_dir=str(temp_dir))

        assert manager._vods_cache == {}

    def test_init_loads_existing_streamers(self, temp_dir):
        """Test that StateManager loads existing streamers from file"""
        state_dir = Path(temp_dir)
        streamers_file = state_dir / "streamers.json"
        streamers_file.write_text(json.dumps({
            "streamers": [{"username": "testuser", "twitch_id": "123", "created_at": "2024-01-15T12:00:00Z"}]
        }))

        manager = StateManager(state_dir=str(state_dir), transcript_dir=str(temp_dir))

        assert "testuser" in manager._streamers_cache


class TestStateManagerVods:
    """Tests for StateManager VOD operations"""

    def test_add_vod(self, mock_state_manager):
        """Test adding a VOD to state"""
        vod = VodRecord(vod_id="123", streamer="testuser", title="Test Stream")
        mock_state_manager.add_vod(vod)

        result = mock_state_manager.get_vod("123")
        assert result is not None
        assert result.vod_id == "123"
        assert result.streamer == "testuser"

    def test_add_vod_creates_streamer_directory(self, mock_state_manager):
        """Test that adding a VOD creates the streamer directory"""
        vod = VodRecord(vod_id="123", streamer="newstreamer")
        mock_state_manager.add_vod(vod)

        streamer_dir = mock_state_manager.transcript_dir / "newstreamer"
        assert streamer_dir.exists()

    def test_update_vod(self, mock_state_manager):
        """Test updating a VOD's fields"""
        vod = VodRecord(vod_id="123", streamer="testuser")
        mock_state_manager.add_vod(vod)

        mock_state_manager.update_vod("123", status=VodStatus.DOWNLOADING.value, title="Updated")

        result = mock_state_manager.get_vod("123")
        assert result.status == "downloading"
        assert result.title == "Updated"

    def test_update_nonexistent_vod(self, mock_state_manager, caplog):
        """Test updating a VOD that doesn't exist"""
        mock_state_manager.update_vod("nonexistent", status="completed")
        # Should log warning but not raise

    def test_get_vod_not_found(self, mock_state_manager):
        """Test getting a VOD that doesn't exist"""
        result = mock_state_manager.get_vod("nonexistent")
        assert result is None

    def test_get_vods_by_status(self, mock_state_manager):
        """Test filtering VODs by status"""
        mock_state_manager.add_vod(VodRecord(vod_id="1", streamer="a", status=VodStatus.PENDING.value))
        mock_state_manager.add_vod(VodRecord(vod_id="2", streamer="b", status=VodStatus.COMPLETED.value))
        mock_state_manager.add_vod(VodRecord(vod_id="3", streamer="c", status=VodStatus.PENDING.value))

        pending = mock_state_manager.get_vods_by_status(VodStatus.PENDING)
        assert len(pending) == 2

        completed = mock_state_manager.get_vods_by_status(VodStatus.COMPLETED)
        assert len(completed) == 1

    def test_get_vods_by_status_string(self, mock_state_manager):
        """Test filtering VODs by status as string"""
        mock_state_manager.add_vod(VodRecord(vod_id="1", streamer="a", status="pending"))

        pending = mock_state_manager.get_vods_by_status("pending")
        assert len(pending) == 1

    def test_get_pending_vods(self, mock_state_manager):
        """Test getting pending VODs"""
        mock_state_manager.add_vod(VodRecord(vod_id="1", streamer="a", status=VodStatus.PENDING.value))
        mock_state_manager.add_vod(VodRecord(vod_id="2", streamer="b", status=VodStatus.COMPLETED.value))

        pending = mock_state_manager.get_pending_vods()
        assert len(pending) == 1
        assert pending[0].vod_id == "1"

    def test_get_all_vods(self, mock_state_manager):
        """Test getting all VODs"""
        mock_state_manager.add_vod(VodRecord(vod_id="1", streamer="a"))
        mock_state_manager.add_vod(VodRecord(vod_id="2", streamer="b"))

        all_vods = mock_state_manager.get_all_vods()
        assert len(all_vods) == 2


class TestStateManagerStreamers:
    """Tests for StateManager streamer operations"""

    def test_add_streamer(self, mock_state_manager):
        """Test adding a streamer"""
        streamer = StreamerRecord(username="testuser", twitch_id="123")
        mock_state_manager.add_streamer(streamer)

        result = mock_state_manager.get_streamer("testuser")
        assert result is not None
        assert result.username == "testuser"
        assert result.twitch_id == "123"

    def test_add_streamer_creates_directory(self, mock_state_manager):
        """Test that adding a streamer creates their directory"""
        streamer = StreamerRecord(username="newstreamer")
        mock_state_manager.add_streamer(streamer)

        streamer_dir = mock_state_manager.transcript_dir / "newstreamer"
        assert streamer_dir.exists()

    def test_get_streamer_not_found(self, mock_state_manager):
        """Test getting a streamer that doesn't exist"""
        result = mock_state_manager.get_streamer("nonexistent")
        assert result is None

    def test_update_streamer(self, mock_state_manager):
        """Test updating a streamer's fields"""
        streamer = StreamerRecord(username="testuser")
        mock_state_manager.add_streamer(streamer)

        mock_state_manager.update_streamer("testuser", twitch_id="999")

        result = mock_state_manager.get_streamer("testuser")
        assert result.twitch_id == "999"

    def test_get_streamers(self, mock_state_manager):
        """Test getting all streamers"""
        mock_state_manager.add_streamer(StreamerRecord(username="user1"))
        mock_state_manager.add_streamer(StreamerRecord(username="user2"))

        streamers = mock_state_manager.get_streamers()
        assert len(streamers) == 2

    def test_get_vods_by_streamer(self, mock_state_manager):
        """Test getting VODs for a specific streamer"""
        mock_state_manager.add_vod(VodRecord(vod_id="1", streamer="alice"))
        mock_state_manager.add_vod(VodRecord(vod_id="2", streamer="bob"))
        mock_state_manager.add_vod(VodRecord(vod_id="3", streamer="alice"))

        alice_vods = mock_state_manager.get_vods_by_streamer("alice")
        assert len(alice_vods) == 2


class TestStateManagerScanCompleted:
    """Tests for scanning completed VODs from filesystem"""

    def test_scan_discovers_transcripts(self, temp_dir):
        """Test that scanning discovers transcript files"""
        # Create a transcript file
        streamer_dir = Path(temp_dir) / "testuser"
        streamer_dir.mkdir()
        (streamer_dir / "1234567890.txt").write_text("Transcript content")

        manager = StateManager(state_dir=str(temp_dir), transcript_dir=str(temp_dir))

        vod = manager.get_vod("1234567890")
        assert vod is not None
        assert vod.streamer == "testuser"
        assert vod.status == VodStatus.COMPLETED.value

    def test_scan_ignores_cache_with_more_info(self, temp_dir):
        """Test that scanning doesn't override cached VODs with more info"""
        # Set up manager with cached VOD
        manager = StateManager(state_dir=str(temp_dir), transcript_dir=str(temp_dir))
        manager.add_vod(VodRecord(
            vod_id="1234567890",
            streamer="testuser",
            title="Full Title",
            duration=3600,
        ))

        # Create transcript file (use exist_ok in case directory was created by add_vod)
        streamer_dir = Path(temp_dir) / "testuser"
        streamer_dir.mkdir(exist_ok=True)
        (streamer_dir / "1234567890.txt").write_text("Transcript")

        # Get VOD - should still have title from cache
        vod = manager.get_vod("1234567890")
        assert vod.title == "Full Title"
        assert vod.duration == 3600


class TestStateManagerFileIO:
    """Tests for StateManager file I/O"""

    def test_save_vods_creates_file(self, mock_state_manager):
        """Test that saving VODs creates the JSON file"""
        mock_state_manager.add_vod(VodRecord(vod_id="123", streamer="testuser"))

        vods_file = mock_state_manager.state_dir / "vods.json"
        assert vods_file.exists()

        data = json.loads(vods_file.read_text())
        assert len(data["vods"]) == 1
        assert data["vods"][0]["vod_id"] == "123"

    def test_save_streamers_creates_file(self, mock_state_manager):
        """Test that saving streamers creates the JSON file"""
        mock_state_manager.add_streamer(StreamerRecord(username="testuser"))

        streamers_file = mock_state_manager.state_dir / "streamers.json"
        assert streamers_file.exists()

        data = json.loads(streamers_file.read_text())
        assert len(data["streamers"]) == 1
        assert data["streamers"][0]["username"] == "testuser"

    def test_is_processed(self, mock_state_manager):
        """Test checking if a VOD has been processed"""
        mock_state_manager.add_vod(VodRecord(vod_id="1", status=VodStatus.COMPLETED.value, streamer="a"))
        mock_state_manager.add_vod(VodRecord(vod_id="2", status=VodStatus.PENDING.value, streamer="a"))

        assert mock_state_manager.is_processed("1") is True
        assert mock_state_manager.is_processed("2") is False
        assert mock_state_manager.is_processed("nonexistent") is False


class TestConvenienceFunctions:
    """Tests for module-level convenience functions"""

    def test_get_state_manager_singleton(self):
        """Test that get_state_manager returns a singleton"""
        import src.state as state_module
        state_module._state_manager = None  # Reset for test

        with patch("src.state.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.state_file_dir = "/tmp/test_state"
            mock_settings.transcript_dir = "/tmp/test_transcripts"
            mock_get_settings.return_value = mock_settings

            manager1 = get_state_manager()
            manager2 = get_state_manager()

            assert manager1 is manager2

        state_module._state_manager = None  # Clean up

    def test_load_processed_vods(self, mock_state_manager):
        """Test loading processed VOD IDs"""
        mock_state_manager.add_vod(VodRecord(vod_id="1", streamer="a", status=VodStatus.COMPLETED.value))
        mock_state_manager.add_vod(VodRecord(vod_id="2", streamer="a", status=VodStatus.FAILED.value))
        mock_state_manager.add_vod(VodRecord(vod_id="3", streamer="a", status=VodStatus.PENDING.value))

        with patch("src.state.get_state_manager", return_value=mock_state_manager):
            processed = load_processed_vods()

        assert "1" in processed  # Completed
        assert "2" in processed  # Failed
        assert "3" not in processed  # Pending

    def test_get_vod_status(self, mock_state_manager):
        """Test getting VOD status"""
        mock_state_manager.add_vod(VodRecord(vod_id="1", streamer="a", status=VodStatus.COMPLETED.value))

        with patch("src.state.get_state_manager", return_value=mock_state_manager):
            status = get_vod_status("1")
            assert status == VodStatus.COMPLETED

            status = get_vod_status("nonexistent")
            assert status is None

    def test_set_vod_status(self, mock_state_manager):
        """Test setting VOD status"""
        mock_state_manager.add_vod(VodRecord(vod_id="1", streamer="a"))

        with patch("src.state.get_state_manager", return_value=mock_state_manager):
            set_vod_status("1", VodStatus.DOWNLOADING)

        vod = mock_state_manager.get_vod("1")
        assert vod.status == VodStatus.DOWNLOADING.value

    def test_get_pending_vods_convenience(self, mock_state_manager):
        """Test get_pending_vods convenience function"""
        mock_state_manager.add_vod(VodRecord(vod_id="1", streamer="a", status=VodStatus.PENDING.value))

        with patch("src.state.get_state_manager", return_value=mock_state_manager):
            vods = get_pending_vods()

        assert len(vods) == 1
        assert vods[0]["vod_id"] == "1"

    def test_add_get_streamer_convenience(self, mock_state_manager):
        """Test add_streamer and get_streamer convenience functions"""
        with patch("src.state.get_state_manager", return_value=mock_state_manager):
            add_streamer("testuser", twitch_id="123")

            streamer = get_streamer("testuser")
            assert streamer is not None
            assert streamer["username"] == "testuser"
            assert streamer["twitch_id"] == "123"

    def test_update_streamer_convenience(self, mock_state_manager):
        """Test update_streamer convenience function"""
        with patch("src.state.get_state_manager", return_value=mock_state_manager):
            add_streamer("testuser")
            update_streamer("testuser", twitch_id="456")

            streamer = get_streamer("testuser")
            assert streamer["twitch_id"] == "456"
