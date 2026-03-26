"""Tests for audio utilities"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audio_utils import (
    split_audio_chunks,
    get_audio_duration,
    cleanup_chunks,
)


class TestGetAudioDuration:
    """Tests for get_audio_duration function"""

    def test_returns_duration(self, mock_subprocess):
        """Test that duration is returned from ffprobe"""
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="125.5\n",
            stderr=""
        )

        duration = get_audio_duration("/path/to/audio.opus")

        assert duration == 125.5

    def test_calls_ffprobe_correctly(self, mock_subprocess):
        """Test that ffprobe is called with correct arguments"""
        duration = get_audio_duration("/path/to/audio.opus")

        # Check that subprocess.run was called
        assert mock_subprocess.called
        call_args = mock_subprocess.call_args[0][0]
        assert "ffprobe" in call_args
        assert "/path/to/audio.opus" in call_args

    def test_raises_on_ffprobe_failure(self, mock_subprocess):
        """Test that RuntimeError is raised when ffprobe fails"""
        mock_subprocess.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="File not found"
        )

        with pytest.raises(RuntimeError, match="ffprobe failed"):
            get_audio_duration("/nonexistent.opus")

    def test_raises_on_parse_error(self, mock_subprocess):
        """Test that RuntimeError is raised when output can't be parsed"""
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="not a number\n",
            stderr=""
        )

        with pytest.raises(RuntimeError, match="Could not parse duration"):
            get_audio_duration("/path/to/audio.opus")


class TestSplitAudioChunks:
    """Tests for split_audio_chunks function"""

    def test_returns_original_if_short(self, temp_dir, mock_subprocess):
        """Test that original file is returned if shorter than chunk duration"""
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="600.0\n",  # 10 minutes
            stderr=""
        )

        # Create a test audio file
        audio_path = os.path.join(temp_dir, "test.opus")
        Path(audio_path).touch()

        chunks = split_audio_chunks(
            audio_path,
            chunk_duration_seconds=1800,  # 30 minutes
            output_dir=temp_dir
        )

        assert chunks == [audio_path]

    def test_splits_long_audio(self, temp_dir):
        """Test that long audio is split into chunks using segment muxer"""
        # Create a test audio file
        audio_path = os.path.join(temp_dir, "test.opus")
        Path(audio_path).touch()

        # Mock subprocess.run to handle both ffprobe and ffmpeg calls
        def mock_subprocess(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("cmd", [])
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)

            # ffprobe call (for duration)
            if "ffprobe" in cmd_str:
                return MagicMock(returncode=0, stdout="7200.0\n", stderr="")
            # ffmpeg segment muxer call
            elif "ffmpeg" in cmd_str and "-segment" in cmd_str:
                # Extract output pattern and create chunk files
                # Pattern is last arg, e.g. "test_chunk_%03d.opus"
                cwd = kwargs.get("cwd", temp_dir)
                for i in range(4):  # 7200 / 1800 = 4 chunks
                    chunk_path = os.path.join(cwd, f"test_chunk_{i:03d}.opus")
                    Path(chunk_path).touch()
                return MagicMock(returncode=0, stdout="", stderr="")
            else:
                return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_subprocess):
            chunks = split_audio_chunks(
                audio_path,
                chunk_duration_seconds=1800,  # 30 minutes
                output_dir=temp_dir
            )

            # Should have 4 chunks for 2 hours with 30 min chunks
            # 7200 / 1800 = 4 chunks
            assert len(chunks) == 4

    def test_creates_output_directory(self, temp_dir, mock_subprocess):
        """Test that output directory is created if it doesn't exist"""
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="600.0\n",
            stderr=""
        )

        audio_path = os.path.join(temp_dir, "test.opus")
        Path(audio_path).touch()

        new_output_dir = os.path.join(temp_dir, "chunks")
        assert not os.path.exists(new_output_dir)

        split_audio_chunks(
            audio_path,
            chunk_duration_seconds=1800,
            output_dir=new_output_dir
        )

        assert os.path.exists(new_output_dir)

    def test_handles_ffmpeg_failure(self, temp_dir, mock_subprocess):
        """Test handling of ffmpeg segment muxer failure - falls back to sequential"""
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="7200.0\n",
            stderr=""
        )

        audio_path = os.path.join(temp_dir, "test.opus")
        Path(audio_path).touch()

        call_count = [0]

        def failing_segment(*args, **kwargs):
            call_count[0] += 1
            cmd = args[0]
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)

            if "ffprobe" in cmd_str:
                return MagicMock(returncode=0, stdout="7200.0\n", stderr="")
            elif "ffmpeg" in cmd_str and "-segment" in cmd_str:
                # Segment muxer fails - triggers fallback
                return MagicMock(returncode=1, stdout="", stderr="Segment error")
            elif "ffmpeg" in cmd_str:
                # Sequential fallback succeeds
                output_path = cmd[-1]
                Path(output_path).touch()
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=failing_segment):
            chunks = split_audio_chunks(
                audio_path,
                chunk_duration_seconds=1800,
                output_dir=temp_dir
            )

            # Should have created chunks via sequential fallback
            assert len(chunks) > 0


class TestCleanupChunks:
    """Tests for cleanup_chunks function"""

    def test_removes_chunk_files(self, temp_dir):
        """Test that chunk files are removed"""
        chunk1 = os.path.join(temp_dir, "chunk1.opus")
        chunk2 = os.path.join(temp_dir, "chunk2.opus")
        Path(chunk1).touch()
        Path(chunk2).touch()

        cleanup_chunks([chunk1, chunk2])

        assert not os.path.exists(chunk1)
        assert not os.path.exists(chunk2)

    def test_preserves_original_file(self, temp_dir):
        """Test that original file is not removed"""
        original = os.path.join(temp_dir, "original.opus")
        chunk = os.path.join(temp_dir, "chunk.opus")
        Path(original).touch()
        Path(chunk).touch()

        cleanup_chunks([original, chunk], original_path=original)

        assert os.path.exists(original)
        assert not os.path.exists(chunk)

    def test_handles_missing_files(self, temp_dir):
        """Test that missing files don't cause errors"""
        nonexistent = os.path.join(temp_dir, "nonexistent.opus")

        # Should not raise
        cleanup_chunks([nonexistent])
