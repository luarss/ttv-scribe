"""Shared fixtures for tests"""

import os
import tempfile
from pathlib import Path
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
