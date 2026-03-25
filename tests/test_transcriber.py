"""Tests for local transcriber"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

from src.transcriber_local import (
    LocalTranscriber,
    save_transcript_to_json,
    export_transcript_to_text,
    _transcribe_chunk_worker,
    create_transcriber,
)


class TestLocalTranscriberModel:
    """Tests for LocalTranscriber model lazy loading"""

    def test_model_lazy_loads(self, mock_settings):
        """Test that model is not loaded until accessed"""
        with patch("src.transcriber_local.get_settings", return_value=mock_settings):
            transcriber = LocalTranscriber()
            assert transcriber._model is None

    def test_model_property_loads_model(self, mock_settings, mock_whisper_model):
        """Test that accessing model property loads the model"""
        with patch("src.transcriber_local.get_settings", return_value=mock_settings):
            with patch("src.transcriber_local.WhisperModel", return_value=mock_whisper_model):
                transcriber = LocalTranscriber()
                model = transcriber.model

                assert transcriber._model is not None
                assert model is mock_whisper_model

    def test_model_cached(self, mock_settings, mock_whisper_model):
        """Test that model is cached after first load"""
        with patch("src.transcriber_local.get_settings", return_value=mock_settings):
            with patch("src.transcriber_local.WhisperModel", return_value=mock_whisper_model) as mock_wm:
                transcriber = LocalTranscriber()

                model1 = transcriber.model
                model2 = transcriber.model

                # WhisperModel should only be instantiated once
                assert mock_wm.call_count == 1


class TestTranscribeVod:
    """Tests for transcribe_vod method"""

    def test_transcribe_short_audio_no_chunking(self, mock_settings, mock_whisper_model, sample_segments):
        """Test transcribing short audio without chunking"""
        with patch("src.transcriber_local.get_settings", return_value=mock_settings):
            with patch("src.transcriber_local.WhisperModel", return_value=mock_whisper_model):
                with patch("src.transcriber_local.get_audio_duration", return_value=600.0):  # 10 min
                    transcriber = LocalTranscriber()

                    text, metadata, cost = transcriber.transcribe_vod(
                        {"vod_id": "123"},
                        "/path/to/audio.opus",
                        max_chunk_duration=1800,  # 30 min
                    )

                    assert text == "Hello everyone.Welcome to the stream.Let's get started."
                    assert "segments_count" in metadata
                    assert cost == 0.0

    def test_transcribe_long_audio_with_chunking(self, mock_settings, mock_whisper_model, temp_dir):
        """Test transcribing long audio with chunking"""
        # Create mock chunk files
        chunk_paths = [
            os.path.join(temp_dir, "chunk_1.opus"),
            os.path.join(temp_dir, "chunk_2.opus"),
        ]
        for p in chunk_paths:
            Path(p).touch()

        with patch("src.transcriber_local.get_settings", return_value=mock_settings):
            with patch("src.transcriber_local.WhisperModel", return_value=mock_whisper_model):
                with patch("src.transcriber_local.get_audio_duration", return_value=7200.0):  # 2 hours
                    with patch("src.transcriber_local.split_audio_chunks", return_value=chunk_paths):
                        with patch("src.transcriber_local.cleanup_chunks"):
                            with patch("src.transcriber_local.NUM_CHUNK_WORKERS", 1):  # Force sequential
                                transcriber = LocalTranscriber()

                                text, metadata, cost = transcriber.transcribe_vod(
                                    {"vod_id": "123"},
                                    "/path/to/audio.opus",
                                    max_chunk_duration=1800,  # 30 min
                                )

                                assert "chunks" in metadata
                                assert metadata["chunks"] == 2

    def test_transcribe_cleans_up_chunks(self, mock_settings, mock_whisper_model, temp_dir):
        """Test that chunk files are cleaned up after transcription"""
        chunk_paths = [
            os.path.join(temp_dir, "chunk_1.opus"),
            os.path.join(temp_dir, "chunk_2.opus"),
        ]
        for p in chunk_paths:
            Path(p).touch()

        with patch("src.transcriber_local.get_settings", return_value=mock_settings):
            with patch("src.transcriber_local.WhisperModel", return_value=mock_whisper_model):
                with patch("src.transcriber_local.get_audio_duration", return_value=7200.0):
                    with patch("src.transcriber_local.split_audio_chunks", return_value=chunk_paths):
                        with patch("src.transcriber_local.cleanup_chunks") as mock_cleanup:
                            with patch("src.transcriber_local.NUM_CHUNK_WORKERS", 1):
                                transcriber = LocalTranscriber()
                                transcriber.transcribe_vod(
                                    {"vod_id": "123"},
                                    "/path/to/audio.opus",
                                    max_chunk_duration=1800,
                                )

                                mock_cleanup.assert_called_once()


class TestExtractMetadata:
    """Tests for _extract_metadata method"""

    def test_extracts_segments_count(self, mock_settings):
        """Test that segments count is extracted"""
        with patch("src.transcriber_local.get_settings", return_value=mock_settings):
            transcriber = LocalTranscriber()
            segments = [
                {"start": 0.0, "end": 5.0, "text": "Hello"},
                {"start": 5.0, "end": 10.0, "text": "World"},
            ]

            metadata = transcriber._extract_metadata(segments)

            assert metadata["segments_count"] == 2

    def test_extracts_key_moments(self, mock_settings):
        """Test that key moments are extracted at 5-minute intervals"""
        with patch("src.transcriber_local.get_settings", return_value=mock_settings):
            transcriber = LocalTranscriber()
            segments = [
                {"start": 0.0, "end": 5.0, "text": "Start"},
                {"start": 300.0, "end": 305.0, "text": "5 minute mark"},  # 5 min
                {"start": 600.0, "end": 605.0, "text": "10 minute mark"},  # 10 min
            ]

            metadata = transcriber._extract_metadata(segments)

            assert len(metadata["key_moments"]) == 2
            assert metadata["key_moments"][0]["time"] == 300
            assert metadata["key_moments"][1]["time"] == 600

    def test_empty_segments(self, mock_settings):
        """Test handling of empty segments list"""
        with patch("src.transcriber_local.get_settings", return_value=mock_settings):
            transcriber = LocalTranscriber()
            metadata = transcriber._extract_metadata([])

            assert metadata == {}


class TestSaveTranscriptToJson:
    """Tests for save_transcript_to_json function"""

    def test_creates_file(self, mock_settings, temp_dir, sample_vod_data):
        """Test that JSON file is created"""
        mock_settings.transcript_dir = temp_dir

        with patch("src.transcriber_local.get_settings", return_value=mock_settings):
            filepath = save_transcript_to_json(
                sample_vod_data,
                "Test transcript",
                {"segments_count": 1},
                0.0,
            )

            assert os.path.exists(filepath)
            assert filepath.endswith(".json")

    def test_json_structure(self, mock_settings, temp_dir, sample_vod_data):
        """Test that JSON has correct structure"""
        mock_settings.transcript_dir = temp_dir

        with patch("src.transcriber_local.get_settings", return_value=mock_settings):
            filepath = save_transcript_to_json(
                sample_vod_data,
                "Test transcript",
                {"segments_count": 1},
                0.0,
            )

            with open(filepath) as f:
                data = json.load(f)

            assert data["vod_id"] == sample_vod_data["vod_id"]
            assert data["streamer"] == sample_vod_data["streamer"]
            assert data["text"] == "Test transcript"
            assert "created_at" in data

    def test_creates_streamer_directory(self, mock_settings, temp_dir, sample_vod_data):
        """Test that streamer subdirectory is created"""
        mock_settings.transcript_dir = temp_dir

        with patch("src.transcriber_local.get_settings", return_value=mock_settings):
            save_transcript_to_json(
                sample_vod_data,
                "Test",
                {},
                0.0,
            )

            streamer_dir = os.path.join(temp_dir, sample_vod_data["streamer"])
            assert os.path.exists(streamer_dir)


class TestExportTranscriptToText:
    """Tests for export_transcript_to_text function"""

    def test_creates_text_file(self, temp_dir, sample_vod_data):
        """Test that text file is created"""
        filepath = export_transcript_to_text(
            sample_vod_data,
            "Test transcript content",
            output_dir=temp_dir,
        )

        assert os.path.exists(filepath)
        assert filepath.endswith(".txt")

    def test_file_content(self, temp_dir, sample_vod_data):
        """Test that file contains transcript text"""
        filepath = export_transcript_to_text(
            sample_vod_data,
            "Test transcript content",
            output_dir=temp_dir,
        )

        with open(filepath) as f:
            content = f.read()

        assert content == "Test transcript content"

    def test_uses_vod_id_as_filename(self, temp_dir, sample_vod_data):
        """Test that VOD ID is used as filename when no title"""
        sample_vod_data["title"] = None

        filepath = export_transcript_to_text(
            sample_vod_data,
            "Test",
            output_dir=temp_dir,
        )

        assert sample_vod_data["vod_id"] in filepath

    def test_sanitizes_title_for_filename(self, temp_dir, sample_vod_data):
        """Test that title is sanitized for filename"""
        sample_vod_data["title"] = "Test/Stream:Title?"

        filepath = export_transcript_to_text(
            sample_vod_data,
            "Test",
            output_dir=temp_dir,
        )

        # Should not contain special characters
        filename = os.path.basename(filepath)
        assert "/" not in filename
        assert ":" not in filename
        assert "?" not in filename


class TestTranscribeChunkWorker:
    """Tests for _transcribe_chunk_worker function"""

    def test_adjusts_timestamps(self, mock_settings, sample_segments):
        """Test that timestamps are adjusted by chunk offset"""
        mock_model = MagicMock()
        mock_segments = [
            MagicMock(start=0.0, end=5.0, text="Hello"),
            MagicMock(start=5.0, end=10.0, text="World"),
        ]
        mock_info = MagicMock(duration=10.0)
        mock_model.transcribe.return_value = (iter(mock_segments), mock_info)

        with patch("src.transcriber_local.WhisperModel", return_value=mock_model):
            result = _transcribe_chunk_worker((
                "/path/to/chunk.opus",
                2,  # chunk_num = 2
                "tiny",
                "cpu",
                "int8",
                5,
                500,
                600,  # chunk_duration = 10 min
            ))

            # Timestamps should be offset by (2-1) * 600 = 600 seconds
            assert result["segments"][0]["start"] == 600.0
            assert result["segments"][0]["end"] == 605.0
            assert result["segments"][1]["start"] == 605.0
            assert result["segments"][1]["end"] == 610.0


class TestCreateTranscriber:
    """Tests for create_transcriber factory function"""

    def test_returns_local_transcriber(self, mock_settings):
        """Test that factory returns LocalTranscriber instance"""
        with patch("src.transcriber_local.get_settings", return_value=mock_settings):
            transcriber = create_transcriber()
            assert isinstance(transcriber, LocalTranscriber)
