"""Shared fixtures for tests"""

import tempfile
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_settings(temp_dir):
    """Mock settings for testing"""
    settings = MagicMock()
    settings.state_file_dir = temp_dir
    settings.transcript_dir = temp_dir
    settings.audio_output_dir = temp_dir
    settings.twitch_client_id = "test_client_id"
    settings.twitch_client_secret = "test_client_secret"
    settings.whisper_model = "tiny"
    settings.whisper_device = "cpu"
    settings.whisper_compute_type = "int8"
    settings.whisper_beam_size = 1
    settings.whisper_vad_min_silence_ms = 500
    return settings


@pytest.fixture
def sample_vod_data():
    """Sample VOD data for testing"""
    return {
        "vod_id": "1234567890",
        "streamer": "testuser",
        "title": "Test Stream Title",
        "duration": 3600,
        "recorded_at": "2024-01-15T12:00:00Z",
        "status": "pending",
    }


@pytest.fixture
def sample_streamer():
    """Sample streamer record for testing"""
    return {
        "username": "testuser",
        "twitch_id": "123456",
        "created_at": "2024-01-15T12:00:00Z",
    }


@pytest.fixture
def sample_segments():
    """Sample Whisper transcription segments"""
    return [
        {"start": 0.0, "end": 5.0, "text": "Hello everyone."},
        {"start": 5.0, "end": 10.0, "text": "Welcome to the stream."},
        {"start": 10.0, "end": 15.0, "text": "Let's get started."},
    ]


@pytest.fixture(autouse=True)
def reset_state_singleton():
    """Reset global state manager singleton before/after each test"""
    import src.state as state_module
    state_module._state_manager = None
    yield
    state_module._state_manager = None


@pytest.fixture
def mock_state_manager(temp_dir):
    """Mock StateManager with in-memory state"""
    from src.state import StateManager

    manager = StateManager(
        state_dir=temp_dir,
        transcript_dir=temp_dir
    )
    return manager


@pytest.fixture
def mock_whisper_model(sample_segments):
    """Mock faster_whisper.WhisperModel"""
    model = MagicMock()

    # Create mock segments
    mock_segments = [
        MagicMock(start=s["start"], end=s["end"], text=s["text"])
        for s in sample_segments
    ]

    # Mock the transcribe method to return (segments, info) tuple
    info = MagicMock(
        language="en",
        language_probability=0.95,
        duration=15.0,
    )
    model.transcribe.return_value = (iter(mock_segments), info)

    return model


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for ffmpeg/ffprobe calls"""
    with patch("subprocess.run") as mock_run:
        # Default: successful ffprobe duration check
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="10.5",
            stderr=""
        )
        yield mock_run


@pytest.fixture
def mock_twitch_response():
    """Sample Twitch API responses"""
    return {
        "token": {
            "access_token": "test_token_123",
            "expires_in": 3600,
            "token_type": "bearer"
        },
        "user": {
            "id": "123456",
            "login": "testuser",
            "display_name": "TestUser",
            "type": "",
            "broadcaster_type": "partner",
            "description": "Test description",
            "profile_image_url": "https://example.com/profile.png",
            "offline_image_url": "https://example.com/offline.png",
            "view_count": 1000,
            "created_at": "2020-01-01T00:00:00Z"
        },
        "vod": {
            "id": "1234567890",
            "user_id": "123456",
            "user_login": "testuser",
            "user_name": "TestUser",
            "title": "Test Stream Title",
            "description": "",
            "created_at": "2024-01-15T12:00:00Z",
            "published_at": "2024-01-15T12:00:00Z",
            "url": "https://www.twitch.tv/videos/1234567890",
            "thumbnail_url": "",
            "viewable": "public",
            "view_count": 100,
            "language": "en",
            "type": "archive",
            "duration": "1h30m45s",
        },
    }


@pytest.fixture
def sample_chunk_result():
    """Sample chunk transcription result for testing"""
    return {
        "chunk_index": 0,
        "segments": [
            {"start": 0.0, "end": 5.0, "text": "Hello everyone."},
            {"start": 5.0, "end": 10.0, "text": "Welcome to the stream."},
        ],
        "text": "Hello everyone. Welcome to the stream.",
        "language": "en",
        "language_probability": 0.95,
        "duration": 600.0,
        "elapsed": 30.0,
    }


@pytest.fixture
def sample_chunk_results():
    """Multiple chunk results for assembly testing"""
    return [
        {
            "chunk_index": 0,
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "First segment."},
            ],
            "text": "First segment.",
            "language": "en",
            "elapsed": 10.0,
        },
        {
            "chunk_index": 1,
            "segments": [
                {"start": 605.0, "end": 610.0, "text": "Second segment."},
            ],
            "text": "Second segment.",
            "language": "en",
            "elapsed": 12.0,
        },
        {
            "chunk_index": 2,
            "segments": [
                {"start": 1210.0, "end": 1215.0, "text": "Third segment."},
            ],
            "text": "Third segment.",
            "language": "en",
            "elapsed": 11.0,
        },
    ]
