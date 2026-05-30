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

    # Step 2: Fetch YouTube transcripts directly (no download needed)
    yt_start = time.time()
    youtube_transcribed = 0
    try:
        youtube_transcribed = fetch_youtube_transcripts(mark_failed=True)
        if youtube_transcribed > 0:
            logger.info(
                f"YouTube transcripts: {youtube_transcribed} fetched "
                f"in {time.time() - yt_start:.1f}s"
            )
    except Exception as e:
        logger.error(f"Error fetching YouTube transcripts: {e}")

    # Step 3 & 4: Download and transcribe in streaming fashion
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
        f"{new_vods} new, {youtube_transcribed} youtube, "
        f"{downloaded} downloaded, {transcribed} transcribed"
    )


def _is_connection_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in (
        "connection refused", "newconnectionerror",
        "failed to establish", "max retries exceeded",
        "socks", "connectionerror",
    ))


def fetch_youtube_transcripts(
    max_vods: Optional[int] = None,
    mark_failed: bool = False,
    proxy: Optional[str] = None,
) -> int:
    """Fetch transcripts for PENDING YouTube VODs via youtube-transcript-api

    Bypasses yt-dlp entirely — gets YouTube's own captions directly.
    No auth, no cookies, no bot detection issues.

    Args:
        max_vods: Maximum number of YouTube VODs to process (None = no limit)
        mark_failed: If True, mark VODs as failed on error. Default False to leave pending for retry.
        proxy: Optional proxy URL(s), comma-separated for rotation
               (e.g. "socks5://a:1,socks5://b:2"). Falls back to direct on connection errors.

    Returns:
        Number of transcripts successfully fetched
    """
    from .state import get_state_manager, VodStatus, Platform
    from .transcriber_local import save_transcript_to_json, export_transcript_to_text

    manager = get_state_manager()
    pending = manager.get_pending_vods()

    yt_vods = [
        v for v in pending
        if v.platform == Platform.YOUTUBE.value
    ]

    if not yt_vods:
        return 0

    total_yt = len(yt_vods)
    if max_vods is not None and len(yt_vods) > max_vods:
        yt_vods = yt_vods[:max_vods]
        logger.info(
            f"Fetching transcripts for {max_vods} of {total_yt} YouTube VODs (capped)"
        )
    else:
        logger.info(f"Fetching transcripts for {total_yt} YouTube VODs")

    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api.proxies import GenericProxyConfig

    proxy_list = [p.strip() for p in proxy.split(",") if p.strip()] if proxy else []
    # Try each proxy in order, then fall back to direct connection
    proxy_candidates: list[Optional[str]] = proxy_list + [None]

    completed = 0

    for vod in yt_vods:
        vod_id = vod.vod_id
        vod_data = vod.to_dict()
        title = vod.title or "Unknown"
        all_connection_errors = True

        for attempt_proxy in proxy_candidates:
            proxy_config = None
            if attempt_proxy:
                proxy_config = GenericProxyConfig(http_url=attempt_proxy, https_url=attempt_proxy)
            proxy_label = f" via {attempt_proxy}" if attempt_proxy else " (direct)"

            api = YouTubeTranscriptApi(proxy_config=proxy_config)
            try:
                transcript = api.fetch(vod_id)
                lines = list(transcript)
                if not lines:
                    raise ValueError("Empty transcript (no captions available)")

                text = " ".join(line.text for line in lines)
                metadata = {
                    "segments_count": len(lines),
                    "source": "youtube_captions",
                }
                save_transcript_to_json(vod_data, text, metadata, cost=0.0)
                export_transcript_to_text(vod_data, text)
                manager.update_vod(vod_id, status=VodStatus.COMPLETED.value)
                completed += 1
                logger.info(
                    f"YouTube transcript OK: {vod_id} ({title[:60]}){proxy_label}"
                    f" — {len(lines)} segments, {len(text)} chars"
                )
                all_connection_errors = False
                break

            except Exception as e:
                if _is_connection_error(e):
                    logger.warning(
                        f"YouTube transcript connection error{proxy_label}: {vod_id} — {e}"
                    )
                    continue
                else:
                    all_connection_errors = False
                    logger.error(f"YouTube transcript failed: {vod_id} ({title[:60]}): {e}")
                    if mark_failed:
                        manager.update_vod(vod_id, status=VodStatus.FAILED.value)
                    break

        if all_connection_errors:
            logger.error(
                f"YouTube transcript failed: {vod_id} ({title[:60]}): "
                f"all {len(proxy_candidates)} proxy attempt(s) refused — leaving pending for retry"
            )

    return completed


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
        from .state import StateManager, Platform
        from .twitch.client import TwitchClient

        downloader = Downloader()
        count = 0

        # Get pending VODs
        pending_vods = get_pending_vods()

        # Sort by duration (shortest first)
        pending_vods.sort(key=lambda v: v.get("duration") or float("inf"))

        if not pending_vods:
            return 0

        # Filter out unavailable VODs
        # For Twitch: check availability via API
        # For Bilibili: skip pre-check, yt-dlp will fail if unavailable
        manager = get_state_manager()
        available_vods = []
        checked_count = 0

        # Separate by platform
        twitch_vods = [
            v for v in pending_vods
            if v.get("platform", Platform.TWITCH.value) == Platform.TWITCH.value
        ]
        bilibili_vods = [
            v for v in pending_vods
            if v.get("platform") == Platform.BILIBILI.value
        ]

        # Check Twitch VOD availability
        with TwitchClient() as twitch:
            for vod_data in twitch_vods:
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

        # Add Bilibili VODs (no pre-check, just attempt download)
        for vod_data in bilibili_vods:
            if max_vods is not None and len(available_vods) >= max_vods:
                break
            checked_count += 1
            available_vods.append(vod_data)

        # YouTube VODs are handled by fetch_youtube_transcripts() — skip here

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
