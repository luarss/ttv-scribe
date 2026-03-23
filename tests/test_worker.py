"""Tests for worker module"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from src.distributed.worker import (
    save_chunk_result,
    transcribe_chunk,
)


class TestTranscribeChunk:
    """Tests for transcribe_chunk function"""

    @patch("src.distributed.worker.WhisperModel")
    @patch("src.distributed.worker.get_settings")
    def test_transcribe_chunk_basic(self, mock_get_settings, mock_whisper_cls, temp_dir, mock_settings):
        """Test basic chunk transcription"""
        # Setup mocks
        mock_get_settings.return_value = mock_settings

        # Create mock model and segments
        mock_model = MagicMock()
        mock_segment1 = MagicMock()
        mock_segment1.start = 0.0
        mock_segment1.end = 5.0
        mock_segment1.text = "Hello world."

        mock_segment2 = MagicMock()
        mock_segment2.start = 5.0
        mock_segment2.end = 10.0
        mock_segment2.text = " Testing."

        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.95
        mock_info.duration = 600.0

        mock_model.transcribe.return_value = ([mock_segment1, mock_segment2], mock_info)
        mock_whisper_cls.return_value = mock_model

        # Create dummy audio file
        audio_path = os.path.join(temp_dir, "chunk.opus")
        with open(audio_path, "wb") as f:
            f.write(b"dummy audio")

        # Execute
        result = transcribe_chunk(
            chunk_path=audio_path,
            chunk_index=2,
            chunk_duration=600,
        )

        # Assert
        assert result["chunk_index"] == 2
        assert len(result["segments"]) == 2
        assert result["language"] == "en"

        # Check timestamp offset was applied (2 * 600 = 1200)
        assert result["segments"][0]["start"] == 1200.0
        assert result["segments"][0]["end"] == 1205.0
        assert result["segments"][1]["start"] == 1205.0
        assert result["segments"][1]["end"] == 1210.0

        # Check combined text
        assert result["text"] == "Hello world. Testing."

    @patch("src.distributed.worker.WhisperModel")
    @patch("src.distributed.worker.get_settings")
    def test_transcribe_chunk_custom_params(self, mock_get_settings, mock_whisper_cls, temp_dir, mock_settings):
        """Test chunk transcription with custom parameters"""
        mock_get_settings.return_value = mock_settings

        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "es"
        mock_info.language_probability = 0.90
        mock_info.duration = 300.0

        mock_model.transcribe.return_value = ([], mock_info)
        mock_whisper_cls.return_value = mock_model

        audio_path = os.path.join(temp_dir, "chunk.opus")
        with open(audio_path, "wb") as f:
            f.write(b"dummy")

        result = transcribe_chunk(
            chunk_path=audio_path,
            chunk_index=0,
            chunk_duration=300,
            model_name="medium",
            device="cuda",
            compute_type="float16",
            beam_size=3,
        )

        # Verify model was created with custom params
        mock_whisper_cls.assert_called_once_with("medium", device="cuda", compute_type="float16")

        # Verify transcribe was called with custom beam_size
        mock_model.transcribe.assert_called_once()
        call_kwargs = mock_model.transcribe.call_args[1]
        assert call_kwargs["beam_size"] == 3


class TestSaveChunkResult:
    """Tests for save_chunk_result function"""

    def test_save_chunk_result(self, temp_dir):
        """Test saving chunk result to JSON"""
        result = {
            "chunk_index": 0,
            "segments": [{"start": 0.0, "end": 5.0, "text": "Test."}],
            "text": "Test.",
            "language": "en",
            "duration": 600.0,
            "elapsed": 30.0,
        }

        output_path = os.path.join(temp_dir, "result-0.json")
        saved_path = save_chunk_result(result, output_path)

        assert saved_path == output_path
        assert os.path.exists(output_path)

        with open(output_path) as f:
            loaded = json.load(f)

        assert loaded["chunk_index"] == 0
        assert loaded["text"] == "Test."
        assert loaded["language"] == "en"
