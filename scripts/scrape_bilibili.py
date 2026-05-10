#!/usr/bin/env python3
"""Scrape Bilibili space pages via Playwright and populate state files.

Extracts streamer info (username, mid) and video list (bvid, title, duration, date)
from Bilibili space pages using Chrome DevTools Protocol via Playwright.
Populates state/streamers.json and state/vods.json through the existing StateManager.

Usage:
    uv run python scripts/scrape_bilibili.py 110532277
    uv run python scripts/scrape_bilibili.py 110532277 41291971
    uv run python scripts/scrape_bilibili.py https://space.bilibili.com/110532277/video
    uv run python scripts/scrape_bilibili.py --dry-run 110532277
    uv run python scripts/scrape_bilibili.py --max-pages 3 110532277

Setup:
    uv pip install -e ".[scrape]"
    playwright install chromium
"""

import argparse
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print(
        "Playwright is not installed. Install with:\n"
        "  uv pip install -e '.[scrape]'\n"
        "  playwright install chromium"
    )
    sys.exit(1)

from src.state import Platform, StateManager, StreamerRecord, VodRecord, VodStatus

# Extract MID from space.bilibili.com URLs
MID_RE = re.compile(r"space\.bilibili\.com/(\d+)")

# Bilibili space video page URL template
SPACE_URL = "https://space.bilibili.com/{mid}/video"

# Scroll wait time (seconds) — gives the page time to fire XHRs and render
SCROLL_WAIT = 2.5

# API endpoint pattern to intercept
ARC_SEARCH_PATH = "/x/space/wbi/arc/search"


def parse_mid(raw: str) -> str | None:
    """Extract a numeric Bilibili MID from a raw input string (MID or space URL)."""
    if raw.isdigit():
        return raw
    match = MID_RE.search(raw)
    if match:
        return match.group(1)
    return None


def parse_duration(length_str: str) -> int | None:
    """Parse Bilibili duration string ("HH:MM:SS" or "MM:SS") to seconds."""
    if not length_str:
        return None
    try:
        parts = length_str.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        pass
    return None


def parse_recorded_at(created_ts: int | None) -> str | None:
    """Convert Bilibili Unix timestamp to ISO 8601 string."""
    if not created_ts:
        return None
    try:
        dt = datetime.fromtimestamp(created_ts, tz=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except (ValueError, OSError):
        return None


def scrape_space_page(
    browser,
    mid: str,
    manager: StateManager,
    dry_run: bool = False,
    max_pages: int | None = None,
) -> tuple[int, int]:
    """Scrape a single Bilibili space page and populate state.

    Args:
        browser: Playwright browser instance.
        mid: Bilibili user MID.
        manager: StateManager instance.
        dry_run: If True, only print what would be added.
        max_pages: Maximum pages of videos to scrape (None = all).

    Returns:
        (new_streamers, new_vods) count.
    """
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1920, "height": 1080},
    )
    page = context.new_page()

    # Collect intercepted API response data
    api_pages: list[dict] = []

    def on_response(response):
        if ARC_SEARCH_PATH in response.url and response.status == 200:
            try:
                data = response.json()
                if data.get("code") == 0:
                    api_pages.append(data)
            except Exception:
                pass  # not JSON or malformed

    page.on("response", on_response)

    # Navigate to space video page
    page.goto(SPACE_URL.format(mid=mid), wait_until="domcontentloaded", timeout=30000)

    # Extract profile from __INITIAL_STATE__
    try:
        page.wait_for_function(
            "() => window.__INITIAL_STATE__ && window.__INITIAL_STATE__.spaceInfo",
            timeout=15000,
        )
    except Exception:
        print(f"  Warning: Could not find __INITIAL_STATE__.spaceInfo for MID {mid}")
        print(f"  The page may be blocked or the MID may not exist.")

    initial_state = page.evaluate("() => window.__INITIAL_STATE__ || {}")
    space_info = initial_state.get("spaceInfo", {})
    username = space_info.get("name", "")
    actual_mid = str(space_info.get("mid", mid))

    if not username:
        # Fallback: try extracting from page title
        title = page.title()
        if "的个人空间" in title:
            username = title.split("的个人空间")[0].strip()

    if not username:
        print(f"  Error: Could not determine username for MID {mid}")
        page.close()
        context.close()
        return 0, 0

    # Add or update streamer
    new_streamers = 0
    existing = manager.get_streamer(username)
    if not existing:
        if not dry_run:
            manager.add_streamer(
                StreamerRecord(
                    username=username,
                    platform=Platform.BILIBILI.value,
                    bilibili_mid=actual_mid,
                )
            )
        new_streamers = 1
        print(f"  + New streamer: {username} (mid={actual_mid})")
    elif not existing.bilibili_mid:
        if not dry_run:
            manager.update_streamer(username, bilibili_mid=actual_mid)
        print(f"  ~ Updated streamer {username} with mid={actual_mid}")
    else:
        print(f"  = Streamer {username} already tracked (mid={existing.bilibili_mid})")

    # Scroll to trigger lazy-loaded video API calls
    scroll_rounds = 0
    prev_count = 0
    no_change_streak = 0

    while max_pages is None or scroll_rounds < max_pages:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(SCROLL_WAIT)

        # Count visible video cards to detect if new content loaded
        current_count = page.evaluate(
            "() => document.querySelectorAll('.video-card, .small-item, .cube-item').length"
        )
        if current_count == prev_count:
            no_change_streak += 1
            if no_change_streak >= 2:
                break
        else:
            no_change_streak = 0
        prev_count = current_count
        scroll_rounds += 1

    # Process all intercepted API responses
    new_vods = 0
    seen_bvids: set[str] = set()

    for response_data in api_pages:
        videos = response_data.get("data", {}).get("list", {}).get("vlist", [])
        for video in videos:
            bvid = video.get("bvid")
            if not bvid or bvid in seen_bvids:
                continue
            seen_bvids.add(bvid)

            # Skip if already tracked
            if manager.get_vod(bvid):
                continue

            duration = parse_duration(video.get("length", ""))
            recorded_at = parse_recorded_at(video.get("created"))
            title = video.get("title", "")

            if not dry_run:
                vod = VodRecord(
                    vod_id=bvid,
                    streamer=username,
                    platform=Platform.BILIBILI.value,
                    title=title if title else None,
                    duration=duration,
                    recorded_at=recorded_at,
                    status=VodStatus.PENDING,
                )
                manager.add_vod(vod)

            new_vods += 1
            dur_str = f" ({duration // 60}:{duration % 60:02d})" if duration else ""
            print(f"  + New VOD: {bvid}{dur_str} - {title[:60]}")

    page.close()
    context.close()
    return new_streamers, new_vods


def main():
    parser = argparse.ArgumentParser(
        description="Scrape Bilibili space pages and populate state files"
    )
    parser.add_argument(
        "mids_or_urls",
        nargs="+",
        help="Bilibili MIDs or space URLs (e.g. 110532277 or https://space.bilibili.com/110532277/video)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum pages of videos to scrape per MID (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be added without modifying state files",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in headed mode (visible window, useful for debugging)",
    )
    args = parser.parse_args()

    mids = []
    for raw in args.mids_or_urls:
        mid = parse_mid(raw)
        if not mid:
            print(f"Error: Could not extract MID from '{raw}'", file=sys.stderr)
            sys.exit(1)
        mids.append(mid)

    manager = StateManager()
    total_streamers = 0
    total_vods = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)

        for mid in mids:
            print(f"\nScraping space page for MID: {mid}")
            try:
                new_s, new_v = scrape_space_page(
                    browser, mid, manager,
                    dry_run=args.dry_run,
                    max_pages=args.max_pages,
                )
                total_streamers += new_s
                total_vods += new_v
                print(f"  -> {new_v} new VODs, {new_s} new streamers")
            except Exception as e:
                print(f"  Error scraping MID {mid}: {e}", file=sys.stderr)

        browser.close()

    print(f"\nDone. {total_streamers} new streamers, {total_vods} new VODs total.")
    if args.dry_run:
        print("(Dry run — no changes written)")


if __name__ == "__main__":
    main()
