"""CLI entry point for recording an IPTV channel segment and splitting into chunks."""

import argparse
import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timezone

from src.config import get_settings
from src.distributed.splitter import prepare_vod_chunks, save_chunk_manifest
from src.iptv.channel_state import load_state, mark_recorded, save_state, sort_by_rotation
from src.iptv.client import IPTVClient
from src.state import VodRecord, VodStatus, get_state_manager

logger = logging.getLogger(__name__)

DEFAULT_RECORD_MINUTES = 30


def record_stream(url: str, output_path: str, duration_seconds: int):
    """Record a segment of an HLS/HTTP stream using ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", url,
        "-t", str(duration_seconds),
        "-vn",
        "-c:a", "libopus",
        "-b:a", "24k",
        "-ar", "16000",
        "-ac", "1",
        output_path,
    ]
    logger.info(f"Recording {url!r} for {duration_seconds}s → {output_path}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration_seconds + 120)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr[-500:]}")
    if not os.path.exists(output_path):
        raise FileNotFoundError(f"ffmpeg output not found: {output_path}")
    logger.info(f"Recording complete: {output_path}")


def _write_empty_matrix():
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write("num_chunks=0\n")
            f.write('matrix={"include": []}\n')
            f.write("channel_id=\n")
    else:
        print("num_chunks=0")
        print('matrix={"include": []}')


def main():
    parser = argparse.ArgumentParser(description="Record IPTV channel segment and split into chunks")
    parser.add_argument(
        "--channel-id",
        default=None,
        help="Specific channel ID to record (default: next in rotation)",
    )
    parser.add_argument(
        "--record-minutes",
        type=int,
        default=DEFAULT_RECORD_MINUTES,
        help=f"Minutes to record (default: {DEFAULT_RECORD_MINUTES})",
    )
    parser.add_argument("--output-dir", default="./chunks", help="Output directory for chunks")
    parser.add_argument(
        "--chunk-duration",
        type=int,
        default=None,
        help="Chunk duration in seconds (default: auto)",
    )
    args = parser.parse_args()

    settings = get_settings()
    state_dir = settings.state_file_dir
    ch_state = load_state(state_dir)

    with IPTVClient() as client:
        channels = client.get_travel_channels()

    if not channels:
        logger.error("No permitted IPTV channels found")
        _write_empty_matrix()
        return

    if args.channel_id:
        candidates = [c for c in channels if c["channel_id"] == args.channel_id]
        if not candidates:
            logger.error(f"Channel {args.channel_id!r} not in permitted channels")
            _write_empty_matrix()
            return
    else:
        # Round-robin: try channels oldest-recorded first
        candidates = sort_by_rotation(channels, ch_state)
        logger.info(
            "Channel rotation order: "
            + ", ".join(
                f"{c['channel_id']} ({ch_state.get('channels', {}).get(c['channel_id'], {}).get('last_recorded_at', 'never')})"
                for c in candidates[:5]
            )
            + ("..." if len(candidates) > 5 else "")
        )

    duration_seconds = args.record_minutes * 60
    recorded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    os.makedirs(args.output_dir, exist_ok=True)

    manifest = None
    channel = None
    for candidate in candidates:
        channel_id = candidate["channel_id"]
        channel_name = candidate["name"]
        stream_url = candidate["url"]
        vod_id = channel_id.replace(".", "_").replace("/", "_")

        logger.info(f"Trying channel: {channel_name} ({channel_id})")

        with tempfile.TemporaryDirectory(prefix="iptv_record_") as tmpdir:
            audio_path = os.path.join(tmpdir, f"{vod_id}.opus")
            try:
                record_stream(stream_url, audio_path, duration_seconds)
            except Exception as e:
                logger.warning(f"Channel {channel_id} unreachable, trying next: {e}")
                continue

            vod_data = {
                "vod_id": vod_id,
                "streamer": channel_name,
                "platform": "iptv",
                "title": f"{channel_name} — live segment",
                "url": stream_url,
                "recorded_at": recorded_at,
            }

            manifest = prepare_vod_chunks(
                vod_id=vod_id,
                audio_path=audio_path,
                vod_data=vod_data,
                chunk_duration=args.chunk_duration,
                output_dir=args.output_dir,
            )
            channel = candidate
            break

    if manifest is None or channel is None:
        logger.error(f"All {len(candidates)} channel(s) failed to record")
        _write_empty_matrix()
        return

    channel_id = channel["channel_id"]
    channel_name = channel["name"]
    vod_id = channel_id.replace(".", "_").replace("/", "_")

    # Persist rotation state so the next run picks the next channel
    ch_state = mark_recorded(channel_id, ch_state)
    save_state(ch_state, state_dir)
    logger.info(f"Marked {channel_id} as recorded at {recorded_at}")

    # Register VOD in vods.json so assemble can update its status later
    manager = get_state_manager()
    manager.add_vod(VodRecord(
        vod_id=vod_id,
        streamer=channel_name,
        platform="iptv",
        title=manifest.get("title"),
        recorded_at=recorded_at,
        status=VodStatus.TRANSCRIBING.value,
    ))

    save_chunk_manifest(manifest, os.path.join(args.output_dir, "manifest.json"))

    matrix = [
        {"index": c["index"], "start_time": c["start_time"], "duration": c["duration"]}
        for c in manifest["chunks"]
    ]
    matrix_json = json.dumps({"include": matrix})
    title = manifest.get("title") or f"{channel_name} live"

    github_output = os.environ.get("GITHUB_OUTPUT")
    delimiter = "ghadelimiter"

    if github_output:
        with open(github_output, "a") as f:
            f.write(f"num_chunks={len(matrix)}\n")
            f.write(f"vod_id={vod_id}\n")
            f.write(f"channel_id={channel_id}\n")
            f.write(f"streamer={channel_name}\n")
            f.write(f"total_duration={manifest['total_duration']}\n")
            f.write(f"chunk_duration={manifest['chunk_duration']}\n")
            f.write(f"matrix={matrix_json}\n")
            f.write(f"title<<{delimiter}\n{title}\n{delimiter}\n")
            f.write(f"recorded_at<<{delimiter}\n{recorded_at}\n{delimiter}\n")
    else:
        print(f"num_chunks={len(matrix)}")
        print(f"vod_id={vod_id}")
        print(f"channel_id={channel_id}")
        print(f"streamer={channel_name}")
        print(f"total_duration={manifest['total_duration']}")
        print(f"chunk_duration={manifest['chunk_duration']}")
        print(f"matrix={matrix_json}")
        print(f"title={title}")
        print(f"recorded_at={recorded_at}")

    print(f"Prepared {len(matrix)} chunks for IPTV channel {channel_id}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    main()
