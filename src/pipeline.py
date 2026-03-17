"""Processing pipeline for TTV-Scribe"""

import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from .config import get_settings
from .monitor import check_for_new_vods
from .monthly_tracker import get_usage_info, update_github_minutes

logger = logging.getLogger(__name__)


def run_pipeline(
    max_duration_minutes: Optional[int] = None, max_vods: Optional[int] = None
):
    """Run the full processing pipeline

    Args:
        max_duration_minutes: Only process VODs shorter than this duration (None = no limit)
        max_vods: Maximum number of VODs to process from queue (None = no limit)
    """
    pipeline_start = time.time()
    logger.info("Starting TTV-Scribe pipeline")

    # Log configuration
    settings = get_settings()
    logger.info(
        f"Transcription config: model={settings.whisper_model}, "
        f"device={settings.whisper_device}, compute_type={settings.whisper_compute_type}, "
        f"beam_size={settings.whisper_beam_size}, num_workers={settings.whisper_num_workers}, "
        f"vad_min_silence_ms={settings.whisper_vad_min_silence_ms}"
    )

    # Log monthly usage (github minutes updated at end to capture current run)
    usage = get_usage_info()
    logger.info(
        f"Monthly usage: {usage['minutes_used']:.1f}/{usage['limit']} minutes "
        f"({usage['remaining']:.1f} remaining for {usage['year']}-{usage['month']:02d})"
    )
    logger.info(
        f"GitHub Actions minutes used: {usage.get('github_minutes_used', 0):.1f}"
    )

    # Step 1: Check for new VODs
    monitor_start = time.time()
    try:
        new_vods = check_for_new_vods(max_duration_minutes=max_duration_minutes)
        logger.info(f"Found {new_vods} new VODs in {time.time() - monitor_start:.1f}s")
    except Exception as e:
        logger.error(f"Error in monitor step: {e}")
        new_vods = 0

    # Step 2 & 3: Download and transcribe in streaming fashion
    # Downloads produce completed VODs that transcription consumes in parallel
    process_start = time.time()
    try:
        downloaded, transcribed = run_streaming_pipeline(max_vods=max_vods)
        logger.info(
            f"Downloaded {downloaded} VODs, transcribed {transcribed} "
            f"in {time.time() - process_start:.1f}s"
        )
    except Exception as e:
        logger.error(f"Error in streaming pipeline: {e}")
        downloaded = 0
        transcribed = 0

    # Update GitHub Actions minutes at the end to include current run
    update_github_minutes()

    pipeline_elapsed = time.time() - pipeline_start
    logger.info(
        f"Pipeline complete in {pipeline_elapsed:.1f}s: "
        f"{new_vods} new, {downloaded} downloaded, {transcribed} transcribed"
    )


def run_streaming_pipeline(max_vods: Optional[int] = None, max_workers: int = 3):
    """Run download and transcription in streaming fashion

    Downloads and transcriptions run in parallel - as each VOD finishes
    downloading, it immediately goes to transcription.

    Args:
        max_vods: Maximum number of VODs to process
        max_workers: Maximum concurrent downloads

    Returns:
        Tuple of (downloaded_count, transcribed_count)
    """
    from .state import get_state_manager, VodStatus, get_pending_vods

    # Queue to pass completed downloads to transcription worker
    download_queue: queue.Queue = queue.Queue()
    transcription_done = threading.Event()

    # Use lists to allow mutation from nested functions
    downloaded_count = [0]
    transcribed_count = [0]

    def download_worker(max_vods: Optional[int], max_workers: int) -> int:
        """Download VODs and put completed ones in queue"""
        from .downloader import Downloader
        from .state import StateManager

        downloader = Downloader()
        count = 0

        # Get pending VODs
        pending_vods = get_pending_vods()

        # Sort by duration (shortest first)
        pending_vods.sort(key=lambda v: v.get("duration") or float("inf"))

        if max_vods is not None:
            pending_vods = pending_vods[:max_vods]

        if not pending_vods:
            return 0

        def download_single_vod(vod_data: dict) -> tuple[bool, str, Optional[str]]:
            """Download a single VOD, return (success, vod_id, audio_path)"""
            # Each thread gets its own StateManager
            manager = StateManager()
            vod_id = vod_data["vod_id"]

            try:
                manager.update_vod(vod_id, status=VodStatus.DOWNLOADING.value)
                audio_path = downloader.download_vod_audio(vod_data)
                logger.info(f"Downloaded VOD {vod_id}")
                return (True, vod_id, audio_path)
            except Exception as e:
                logger.error(f"Failed to download VOD {vod_id}: {e}")
                manager.update_vod(vod_id, status=VodStatus.FAILED.value)
                return (False, vod_id, None)

        # Run downloads in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_vod = {
                executor.submit(download_single_vod, vod_data): vod_data
                for vod_data in pending_vods
            }

            for future in as_completed(future_to_vod):
                success, _, audio_path = future.result()
                if success and audio_path:
                    # Put completed download in queue for transcription
                    vod_data = future_to_vod[future]
                    download_queue.put((vod_data, audio_path))
                    count += 1

        return count

    def transcribe_worker() -> int:
        """Transcribe VODs from the queue"""
        from .transcriber_local import (
            save_transcript_to_json,
            export_transcript_to_text,
        )
        from .transcriber_local import (
            LocalTranscriber,
            get_remaining_minutes,
            add_minutes_used,
        )

        transcriber = LocalTranscriber()
        count = 0
        manager = get_state_manager()

        while not transcription_done.is_set() or not download_queue.empty():
            try:
                # Wait for next item with timeout
                vod_data, audio_path = download_queue.get(timeout=5)
                vod_id = vod_data["vod_id"]

                # Check monthly limit
                duration_seconds = vod_data.get("duration")
                if duration_seconds:
                    estimated_minutes = duration_seconds / 60
                    remaining = get_remaining_minutes()
                    if remaining < estimated_minutes:
                        logger.warning(
                            f"Skipping VOD {vod_id} - not enough monthly minutes"
                        )
                        manager.update_vod(vod_id, status=VodStatus.FAILED.value)
                        download_queue.task_done()
                        continue

                try:
                    manager.update_vod(vod_id, status=VodStatus.TRANSCRIBING.value)

                    # Transcribe
                    text, metadata, cost = transcriber.transcribe_vod(
                        vod_data, audio_path
                    )

                    # Save transcript
                    transcript_path = save_transcript_to_json(
                        vod_data, text, metadata, cost
                    )
                    export_transcript_to_text(vod_data, text)

                    # Track minutes
                    actual_duration = metadata.get(
                        "total_duration_seconds", duration_seconds or 0
                    )
                    if actual_duration:
                        add_minutes_used(actual_duration / 60)

                    # Mark complete
                    manager.update_vod(
                        vod_id,
                        status=VodStatus.COMPLETED.value,
                        transcript_path=transcript_path,
                    )

                    count += 1
                    logger.info(f"Completed transcription for VOD {vod_id}")

                except Exception as e:
                    logger.error(f"Failed to transcribe VOD {vod_id}: {e}")
                    manager.update_vod(vod_id, status=VodStatus.FAILED.value)

                finally:
                    # Cleanup audio
                    from .downloader import Downloader

                    downloader = Downloader()
                    downloader.cleanup_audio(audio_path)
                    download_queue.task_done()

            except queue.Empty:
                # No items available, keep waiting
                continue
            except Exception as e:
                logger.error(f"Error in transcription worker: {e}")

        return count

    # Start download worker in thread (producer)
    download_thread = threading.Thread(
        target=lambda: downloaded_count.__setitem__(
            0, download_worker(max_vods, max_workers)
        )
    )
    download_thread.start()

    # Start transcription worker (consumer)
    transcription_thread = threading.Thread(
        target=lambda: transcribed_count.__setitem__(0, transcribe_worker())
    )
    transcription_thread.start()

    # Wait for download worker to finish
    download_thread.join()

    # Signal transcription worker to stop and wait for it
    transcription_done.set()
    transcription_thread.join()

    return downloaded_count[0], transcribed_count[0]


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    run_pipeline()
