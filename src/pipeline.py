"""Processing pipeline for TTV-Scribe"""

import logging
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from .config import get_settings
from .monitor import check_for_new_vods

logger = logging.getLogger(__name__)

# Default to CPU count - 1 for transcription workers (leave 1 core for downloads)
DEFAULT_NUM_TRANSCRIPTION_WORKERS = max(1, (os.cpu_count() or 4) - 1)


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
        f"beam_size={settings.whisper_beam_size}, vad_min_silence_ms={settings.whisper_vad_min_silence_ms}"
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

    pipeline_elapsed = time.time() - pipeline_start
    logger.info(
        f"Pipeline complete in {pipeline_elapsed:.1f}s: "
        f"{new_vods} new, {downloaded} downloaded, {transcribed} transcribed"
    )


def run_streaming_pipeline(
    max_vods: Optional[int] = None,
    max_workers: int = 3,
    num_transcription_workers: Optional[int] = None,
):
    """Run download and transcription in streaming fashion

    Downloads and transcriptions run in parallel - as each VOD finishes
    downloading, it immediately goes to transcription.

    Args:
        max_vods: Maximum number of VODs to process
        max_workers: Maximum concurrent downloads
        num_transcription_workers: Number of transcription workers (default: CPU count - 1)

    Returns:
        Tuple of (downloaded_count, transcribed_count)
    """
    from .state import get_state_manager, VodStatus, get_pending_vods

    if num_transcription_workers is None:
        num_transcription_workers = DEFAULT_NUM_TRANSCRIPTION_WORKERS

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
        from .twitch.client import TwitchClient

        downloader = Downloader()
        count = 0

        # Get pending VODs
        pending_vods = get_pending_vods()

        # Sort by duration (shortest first)
        pending_vods.sort(key=lambda v: v.get("duration") or float("inf"))

        if not pending_vods:
            return 0

        # Filter out unavailable VODs (deleted/expired from Twitch)
        # Check availability BEFORE slicing to max_vods so we fill the quota
        manager = get_state_manager()
        available_vods = []
        checked_count = 0

        with TwitchClient() as twitch:
            for vod_data in pending_vods:
                # Stop if we have enough available VODs
                if max_vods is not None and len(available_vods) >= max_vods:
                    break

                vod_id = vod_data["vod_id"]
                checked_count += 1
                video = twitch.get_video_by_id(vod_id)
                if video is None:
                    logger.info(f"VOD {vod_id} no longer available on Twitch, marking as failed")
                    manager.update_vod(vod_id, status=VodStatus.FAILED.value)
                else:
                    available_vods.append(vod_data)

        logger.info(f"Checked {checked_count} VODs, {len(available_vods)} available")

        if not available_vods:
            logger.info("No available VODs to process")
            return 0

        pending_vods = available_vods

        def download_single_vod(vod_data: dict) -> tuple[bool, str, Optional[str]]:
            """Download a single VOD, return (success, vod_id, audio_path)"""
            # Each thread gets its own StateManager
            manager = StateManager()
            vod_id = vod_data["vod_id"]

            try:
                manager.update_vod(vod_id, status=VodStatus.DOWNLOADING.value)
                audio_path = downloader.download_vod_audio(vod_data)
                logger.debug(f"Downloaded VOD {vod_id}")
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

    def transcribe_worker(downloader: "Downloader") -> int:
        """Transcribe VODs from the queue

        Args:
            downloader: Shared Downloader instance for audio cleanup
        """
        from .transcriber_local import (
            save_transcript_to_json,
            export_transcript_to_text,
            LocalTranscriber,
        )

        transcriber = LocalTranscriber()
        count = 0
        manager = get_state_manager()

        while not transcription_done.is_set() or not download_queue.empty():
            try:
                # Wait for next item with timeout
                vod_data, audio_path = download_queue.get(timeout=5)
                vod_id = vod_data["vod_id"]

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

                    # Mark complete
                    manager.update_vod(
                        vod_id,
                        status=VodStatus.COMPLETED.value,
                        transcript_path=transcript_path,
                    )

                    count += 1
                    title = vod_data.get("title", "Unknown")
                    logger.info(f"Completed VOD {vod_id} ({title})")

                except Exception as e:
                    logger.error(f"Failed to transcribe VOD {vod_id}: {e}")
                    manager.update_vod(vod_id, status=VodStatus.FAILED.value)

                finally:
                    # Cleanup audio using shared downloader
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

    # Create shared downloader for transcription workers (for audio cleanup)
    from .downloader import Downloader

    shared_downloader = Downloader()

    # Start multiple transcription workers (consumers)
    transcription_threads = []
    for _ in range(num_transcription_workers):
        t = threading.Thread(
            target=lambda: transcribed_count.__setitem__(
                0, transcribed_count[0] + transcribe_worker(shared_downloader)
            )
        )
        t.start()
        transcription_threads.append(t)
    logger.info(f"Started {num_transcription_workers} transcription workers")

    # Wait for download worker to finish
    download_thread.join()

    # Signal transcription workers to stop and wait for them
    transcription_done.set()
    for t in transcription_threads:
        t.join()

    return downloaded_count[0], transcribed_count[0]


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    run_pipeline()
