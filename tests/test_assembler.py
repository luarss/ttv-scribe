"""Tests for assembler module"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from src.distributed.assembler import (
    _extract_key_moments,
    assemble_transcript,
    load_chunk_result,
    load_chunk_results_from_dir,
    save_transcript,
    update_vod_status,
)


class TestLoadChunkResult:
    """Tests for load_chunk_result function"""

    def test_load_chunk_result(self, temp_dir):
        """Test loading a chunk result from JSON"""
        result = {
            "chunk_index": 0,
            "segments": [{"start": 0.0, "end": 5.0, "text": "Test."}],
            "text": "Test.",
        }

        result_path = os.path.join(temp_dir, "result-0.json")
        with open(result_path, "w") as f:
            json.dump(result, f, ensure_ascii=False)

        loaded = load_chunk_result(result_path)
        assert loaded == result


class TestLoadChunkResultsFromDir:
    """Tests for load_chunk_results_from_dir function"""

    def test_load_all_results(self, temp_dir):
        """Test loading all chunk results from directory"""
        # Create multiple result files
        for i in range(3):
            result = {
                "chunk_index": i,
                "segments": [{"start": i * 600, "end": i * 600 + 5, "text": f"Chunk {i}."}],
                "text": f"Chunk {i}.",
            }
            with open(os.path.join(temp_dir, f"result-{i}.json"), "w") as f:
                json.dump(result, f, ensure_ascii=False)

        # Also create a non-result file to ensure it's ignored
        with open(os.path.join(temp_dir, "other.json"), "w") as f:
            json.dump({"foo": "bar"}, f, ensure_ascii=False)

        results = load_chunk_results_from_dir(temp_dir)

        assert len(results) == 3
        # Results should be sorted by filename (result-0, result-1, result-2)
        assert results[0]["chunk_index"] == 0
        assert results[1]["chunk_index"] == 1
        assert results[2]["chunk_index"] == 2


class TestAssembleTranscript:
    """Tests for assemble_transcript function"""

    def test_assemble_transcript(self, sample_chunk_results):
        """Test assembling chunk results into final transcript"""
        transcript = assemble_transcript(
            vod_id="1234567890",
            streamer="testuser",
            title="Test Stream",
            recorded_at="2024-01-15T12:00:00Z",
            total_duration=1800.0,
            chunk_results=sample_chunk_results,
        )

        assert transcript["vod_id"] == "1234567890"
        assert transcript["streamer"] == "testuser"
        assert transcript["title"] == "Test Stream"
        assert transcript["text"] == "First segment.Second segment.Third segment."
        assert transcript["cost"] == 0.0
        assert "created_at" in transcript

        # Check metadata
        assert transcript["metadata"]["segments_count"] == 3
        assert transcript["metadata"]["chunks"] == 3
        assert transcript["metadata"]["total_duration_seconds"] == 1800.0
        assert "en" in transcript["metadata"]["languages"]

    def test_assemble_transcript_orders_segments(self):
        """Test that segments are ordered by timestamp"""
        # Provide results out of order
        chunk_results = [
            {
                "chunk_index": 2,
                "segments": [{"start": 1200.0, "end": 1205.0, "text": "Third."}],
                "elapsed": 10.0,
            },
            {
                "chunk_index": 0,
                "segments": [{"start": 0.0, "end": 5.0, "text": "First."}],
                "elapsed": 10.0,
            },
            {
                "chunk_index": 1,
                "segments": [{"start": 600.0, "end": 605.0, "text": "Second."}],
                "elapsed": 10.0,
            },
        ]

        transcript = assemble_transcript(
            vod_id="test",
            streamer="testuser",
            title=None,
            recorded_at=None,
            total_duration=1800.0,
            chunk_results=chunk_results,
        )

        # Segments should be in timestamp order
        assert transcript["segments"][0]["start"] == 0.0
        assert transcript["segments"][1]["start"] == 600.0
        assert transcript["segments"][2]["start"] == 1200.0


class TestExtractKeyMoments:
    """Tests for _extract_key_moments function"""

    def test_extract_key_moments(self):
        """Test key moment extraction at 5-minute intervals"""
        segments = [
            {"start": 0.0, "text": "Start of stream."},
            {"start": 300.0, "text": "Five minute mark."},
            {"start": 600.0, "text": "Ten minute mark."},
            {"start": 900.0, "text": "Fifteen minute mark."},
            {"start": 1200.0, "text": "Twenty minute mark."},
        ]

        key_moments = _extract_key_moments(segments, interval=300)

        # Should have key moments at 300, 600, 900, 1200
        assert len(key_moments) == 4
        assert key_moments[0]["time"] == 300
        assert key_moments[1]["time"] == 600

    def test_extract_key_moments_truncates_text(self):
        """Test that key moment text is truncated to 200 chars"""
        long_text = "A" * 500
        segments = [{"start": 300.0, "text": long_text}]

        key_moments = _extract_key_moments(segments, interval=300)

        assert len(key_moments) == 1
        assert len(key_moments[0]["text"]) == 200


class TestSaveTranscript:
    """Tests for save_transcript function"""

    @patch("src.distributed.assembler.get_settings")
    def test_save_transcript(self, mock_get_settings, temp_dir, mock_settings):
        """Test saving transcript to JSON file"""
        mock_settings.transcript_dir = temp_dir
        mock_get_settings.return_value = mock_settings

        transcript = {
            "vod_id": "1234567890",
            "streamer": "testuser",
            "title": "Test Stream",
            "text": "Hello world.",
            "metadata": {"segments_count": 1},
        }

        path = save_transcript(transcript)

        expected_path = os.path.join(temp_dir, "testuser", "1234567890.json")
        assert path == expected_path
        assert os.path.exists(expected_path)

        with open(expected_path) as f:
            loaded = json.load(f)

        assert loaded["vod_id"] == "1234567890"
        assert loaded["text"] == "Hello world."

    @patch("src.distributed.assembler.get_settings")
    def test_save_transcript_custom_dir(self, mock_get_settings, temp_dir, mock_settings):
        """Test saving transcript to custom directory"""
        mock_get_settings.return_value = mock_settings

        custom_dir = os.path.join(temp_dir, "custom")
        os.makedirs(custom_dir)

        transcript = {
            "vod_id": "test",
            "streamer": "user",
            "text": "Test.",
            "metadata": {},
        }

        path = save_transcript(transcript, output_dir=custom_dir)

        assert path == os.path.join(custom_dir, "user", "test.json")


class TestUpdateVodStatus:
    """Tests for update_vod_status function"""

    @patch("src.distributed.assembler.get_state_manager")
    def test_update_vod_status(self, mock_get_manager):
        """Test updating VOD status in state"""
        mock_manager = MagicMock()
        mock_get_manager.return_value = mock_manager

        update_vod_status("1234567890", "/transcripts/test.json", status="completed")

        mock_manager.update_vod.assert_called_once_with(
            "1234567890",
            status="completed",
            transcript_path="/transcripts/test.json",
        )
