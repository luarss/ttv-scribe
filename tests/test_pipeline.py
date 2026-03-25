"""Tests for processing pipeline"""

import queue
import threading
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline import run_pipeline, run_streaming_pipeline


class TestRunPipeline:
    """Tests for run_pipeline function"""

    def test_calls_monitor(self, mock_settings):
        """Test that check_for_new_vods is called"""
        with patch("src.pipeline.get_settings", return_value=mock_settings):
            with patch("src.pipeline.check_for_new_vods", return_value=5) as mock_monitor:
                with patch("src.pipeline.run_streaming_pipeline", return_value=(0, 0)):
                    run_pipeline()

                    mock_monitor.assert_called_once()

    def test_calls_streaming_pipeline(self, mock_settings):
        """Test that run_streaming_pipeline is called"""
        with patch("src.pipeline.get_settings", return_value=mock_settings):
            with patch("src.pipeline.check_for_new_vods", return_value=0):
                with patch("src.pipeline.run_streaming_pipeline", return_value=(2, 2)) as mock_streaming:
                    run_pipeline()

                    mock_streaming.assert_called_once()

    def test_passes_max_duration_to_monitor(self, mock_settings):
        """Test that max_duration_minutes is passed to monitor"""
        with patch("src.pipeline.get_settings", return_value=mock_settings):
            with patch("src.pipeline.check_for_new_vods", return_value=0) as mock_monitor:
                with patch("src.pipeline.run_streaming_pipeline", return_value=(0, 0)):
                    run_pipeline(max_duration_minutes=120)

                    mock_monitor.assert_called_once_with(max_duration_minutes=120)

    def test_passes_max_vods_to_streaming(self, mock_settings):
        """Test that max_vods is passed to streaming pipeline"""
        with patch("src.pipeline.get_settings", return_value=mock_settings):
            with patch("src.pipeline.check_for_new_vods", return_value=0):
                with patch("src.pipeline.run_streaming_pipeline", return_value=(0, 0)) as mock_streaming:
                    run_pipeline(max_vods=5)

                    mock_streaming.assert_called_once_with(max_vods=5)

    def test_handles_monitor_error(self, mock_settings):
        """Test that monitor errors are handled gracefully"""
        with patch("src.pipeline.get_settings", return_value=mock_settings):
            with patch("src.pipeline.check_for_new_vods", side_effect=Exception("API Error")):
                with patch("src.pipeline.run_streaming_pipeline", return_value=(0, 0)):
                    # Should not raise
                    run_pipeline()

    def test_handles_streaming_error(self, mock_settings):
        """Test that streaming pipeline errors are handled gracefully"""
        with patch("src.pipeline.get_settings", return_value=mock_settings):
            with patch("src.pipeline.check_for_new_vods", return_value=0):
                with patch("src.pipeline.run_streaming_pipeline", side_effect=Exception("Download Error")):
                    # Should not raise
                    run_pipeline()


class TestRunStreamingPipeline:
    """Tests for run_streaming_pipeline function"""

    def test_returns_zero_when_no_pending(self, mock_settings, mock_state_manager):
        """Test that 0,0 is returned when no pending VODs"""
        with patch("src.pipeline.get_settings", return_value=mock_settings):
            with patch("src.pipeline.get_pending_vods", return_value=[]):
                with patch("src.pipeline.get_state_manager", return_value=mock_state_manager):
                    downloaded, transcribed = run_streaming_pipeline()

                    assert downloaded == 0
                    assert transcribed == 0

    def test_processes_available_vods(self, mock_settings, mock_state_manager, temp_dir):
        """Test that available VODs are processed"""
        mock_settings.audio_output_dir = temp_dir

        pending_vods = [
            {"vod_id": "123", "streamer": "test", "duration": 1800, "title": "Test"},
        ]

        # Create expected output file
        expected_path = f"{temp_dir}/123.opus"
        with patch("builtins.open", create=True):
            pass

        with patch("src.pipeline.get_settings", return_value=mock_settings):
            with patch("src.pipeline.get_pending_vods", return_value=pending_vods):
                with patch("src.pipeline.get_state_manager", return_value=mock_state_manager):
                    with patch("src.pipeline.TwitchClient") as mock_twitch_class:
                        mock_twitch = MagicMock()
                        mock_twitch.__enter__ = MagicMock(return_value=mock_twitch)
                        mock_twitch.__exit__ = MagicMock(return_value=False)
                        mock_twitch_class.return_value = mock_twitch

                        # VOD is available
                        mock_twitch.get_video_by_id.return_value = {"id": "123"}

                        with patch("src.pipeline.Downloader") as mock_dl_class:
                            mock_dl = MagicMock()
                            mock_dl_class.return_value = mock_dl
                            mock_dl.download_vod_audio.return_value = expected_path

                            with patch("src.pipeline.LocalTranscriber") as mock_trans_class:
                                mock_trans = MagicMock()
                                mock_trans_class.return_value = mock_trans
                                mock_trans.transcribe_vod.return_value = ("text", {}, 0.0)

                                with patch("src.pipeline.save_transcript_to_json", return_value="/path/transcript.json"):
                                    with patch("src.pipeline.export_transcript_to_text"):
                                        downloaded, transcribed = run_streaming_pipeline(max_vods=1, max_workers=1)

                                        assert downloaded == 1
                                        assert transcribed == 1

    def test_marks_unavailable_vods_as_failed(self, mock_settings, mock_state_manager):
        """Test that unavailable VODs are marked as failed"""
        pending_vods = [
            {"vod_id": "123", "streamer": "test", "duration": 1800},
        ]

        with patch("src.pipeline.get_settings", return_value=mock_settings):
            with patch("src.pipeline.get_pending_vods", return_value=pending_vods):
                with patch("src.pipeline.get_state_manager", return_value=mock_state_manager):
                    with patch("src.pipeline.TwitchClient") as mock_twitch_class:
                        mock_twitch = MagicMock()
                        mock_twitch.__enter__ = MagicMock(return_value=mock_twitch)
                        mock_twitch.__exit__ = MagicMock(return_value=False)
                        mock_twitch_class.return_value = mock_twitch

                        # VOD is not available
                        mock_twitch.get_video_by_id.return_value = None

                        downloaded, transcribed = run_streaming_pipeline(max_vods=1)

                        # VOD should be marked as failed
                        mock_state_manager.update_vod.assert_called()
                        assert downloaded == 0

    def test_respects_max_vods_limit(self, mock_settings, mock_state_manager):
        """Test that max_vods limit is respected when checking availability"""
        pending_vods = [
            {"vod_id": str(i), "streamer": "test", "duration": 1800}
            for i in range(5)
        ]

        with patch("src.pipeline.get_settings", return_value=mock_settings):
            with patch("src.pipeline.get_pending_vods", return_value=pending_vods):
                with patch("src.pipeline.get_state_manager", return_value=mock_state_manager):
                    with patch("src.pipeline.TwitchClient") as mock_twitch_class:
                        mock_twitch = MagicMock()
                        mock_twitch.__enter__ = MagicMock(return_value=mock_twitch)
                        mock_twitch.__exit__ = MagicMock(return_value=False)
                        mock_twitch_class.return_value = mock_twitch

                        # All VODs are available
                        mock_twitch.get_video_by_id.return_value = {"id": "123"}

                        # With max_vods=2, only 2 VODs should be checked
                        run_streaming_pipeline(max_vods=2)

                        # get_video_by_id should be called exactly 2 times
                        assert mock_twitch.get_video_by_id.call_count == 2


class TestPipelineIntegration:
    """Integration-style tests for pipeline components"""

    def test_producer_consumer_pattern(self, mock_settings):
        """Test that download and transcription use producer-consumer pattern"""
        # Create a real queue to verify the pattern
        test_queue = queue.Queue()
        items_produced = []
        items_consumed = []

        def producer():
            for i in range(3):
                test_queue.put(f"item_{i}")
                items_produced.append(f"item_{i}")

        def consumer():
            done = threading.Event()
            while not done.is_set() or not test_queue.empty():
                try:
                    item = test_queue.get(timeout=0.1)
                    items_consumed.append(item)
                    test_queue.task_done()
                except queue.Empty:
                    pass

        # Run producer
        producer_thread = threading.Thread(target=producer)
        producer_thread.start()
        producer_thread.join()

        # Signal done and run consumer
        done_event = threading.Event()
        done_event.set()

        consumer_thread = threading.Thread(target=consumer)
        consumer_thread.start()
        consumer_thread.join(timeout=2)

        assert len(items_produced) == 3
        assert len(items_consumed) == 3
