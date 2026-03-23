"""Tests for splitter module"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.distributed.splitter import (
    download_vod_audio,
    prepare_vod_chunks,
    save_chunk_manifest,
)


class TestDownloadVodAudio:
    """Tests for download_vod_audio function"""

    @patch("src.distributed.splitter.get_state_manager")
    @patch("src.distributed.splitter.Downloader")
    def test_download_vod_audio_success(self, mock_downloader_cls, mock_get_manager, sample_vod_data):
        """Test successful VOD download"""
        # Setup mocks
        mock_manager = MagicMock()
        mock_vod_record = MagicMock()
        mock_vod_record.to_dict.return_value = sample_vod_data
        mock_manager.get_vod.return_value = mock_vod_record
        mock_get_manager.return_value = mock_manager

        mock_downloader = MagicMock()
        mock_downloader.download_vod_audio.return_value = "/tmp/audio.opus"
        mock_downloader_cls.return_value = mock_downloader

        # Execute
        audio_path, vod_dict = download_vod_audio("1234567890")

        # Assert
        assert audio_path == "/tmp/audio.opus"
        assert vod_dict == sample_vod_data
        mock_manager.update_vod.assert_called_once()

    @patch("src.distributed.splitter.get_state_manager")
    def test_download_vod_audio_not_found(self, mock_get_manager):
        """Test VOD not found raises ValueError"""
        mock_manager = MagicMock()
        mock_manager.get_vod.return_value = None
        mock_get_manager.return_value = mock_manager

        with pytest.raises(ValueError, match="VOD 999 not found"):
            download_vod_audio("999")


class TestPrepareVodChunks:
    """Tests for prepare_vod_chunks function"""

    @patch("src.distributed.splitter.get_audio_duration")
    @patch("src.distributed.splitter.split_audio_chunks")
    def test_prepare_vod_chunks(self, mock_split, mock_duration, temp_dir, sample_vod_data):
        """Test chunk preparation"""
        # Setup mocks
        mock_duration.side_effect = [1800.0, 600.0, 600.0, 600.0]  # Total, then each chunk
        mock_split.return_value = [
            f"{temp_dir}/chunk_001.opus",
            f"{temp_dir}/chunk_002.opus",
            f"{temp_dir}/chunk_003.opus",
        ]

        # Create dummy chunk files
        for i in range(1, 4):
            Path(f"{temp_dir}/chunk_{i:03d}.opus").touch()

        # Execute
        manifest = prepare_vod_chunks(
            vod_id="1234567890",
            audio_path="/tmp/audio.opus",
            vod_data=sample_vod_data,
            chunk_duration=600,
            output_dir=temp_dir,
        )

        # Assert
        assert manifest["vod_id"] == "1234567890"
        assert manifest["streamer"] == "testuser"
        assert manifest["total_duration"] == 1800.0
        assert manifest["chunk_duration"] == 600
        assert len(manifest["chunks"]) == 3

        # Check chunk metadata
        for i, chunk in enumerate(manifest["chunks"]):
            assert chunk["index"] == i
            assert chunk["start_time"] == i * 600


class TestSaveChunkManifest:
    """Tests for save_chunk_manifest function"""

    def test_save_chunk_manifest(self, temp_dir):
        """Test saving manifest to JSON"""
        manifest = {
            "vod_id": "1234567890",
            "streamer": "testuser",
            "title": "Test Stream",
            "recorded_at": "2024-01-15T12:00:00Z",
            "total_duration": 1800.0,
            "chunk_duration": 600,
            "chunks": [{"index": 0, "path": "/tmp/chunk.opus"}],
        }

        output_path = os.path.join(temp_dir, "manifest.json")
        save_chunk_manifest(manifest, output_path)

        # Verify file exists and contains expected data
        assert os.path.exists(output_path)
        with open(output_path) as f:
            saved = json.load(f)

        assert saved["vod_id"] == "1234567890"
        assert saved["num_chunks"] == 1
        # Path should not be included in serializable version
        assert "chunks" not in saved
