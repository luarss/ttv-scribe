"""IPTV client for fetching travel channels from iptv-org"""

import json
import logging
import os
import re

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

TRAVEL_M3U_URL = "https://iptv-org.github.io/iptv/categories/travel.m3u"


class IPTVClient:
    """Fetches and filters travel livestreams from iptv-org"""

    def __init__(self):
        self.settings = get_settings()
        self._client = httpx.Client(timeout=30.0)
        self._banlist: set[str] = self._load_banlist()
        self._allowlist: dict[str, dict] | None = self._load_allowlist()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._client.close()

    def _load_banlist(self) -> set[str]:
        banlist_path = os.path.join(self.settings.state_file_dir, "iptv_banlist.json")
        try:
            with open(banlist_path) as f:
                data = json.load(f)
            ids = {entry["channel_id"] for entry in data.get("banned_channels", [])}
            logger.debug(f"Loaded {len(ids)} banned IPTV channels")
            return ids
        except FileNotFoundError:
            logger.warning(f"No IPTV banlist found at {banlist_path}")
            return set()

    def _load_allowlist(self) -> dict[str, dict] | None:
        """Load allowlist keyed by channel_id. Returns None if file absent (allow all)."""
        allowlist_path = os.path.join(self.settings.state_file_dir, "iptv_allowlist.json")
        try:
            with open(allowlist_path) as f:
                data = json.load(f)
            entries = {e["channel_id"]: e for e in data.get("allowed_channels", [])}
            logger.debug(f"Loaded {len(entries)} allowed IPTV channels")
            return entries
        except FileNotFoundError:
            logger.debug("No IPTV allowlist found; all non-banned channels permitted")
            return None

    def _parse_m3u(self, content: str) -> list[dict]:
        """Parse M3U playlist into a list of channel dicts"""
        channels = []
        lines = content.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line.startswith("#EXTINF"):
                i += 1
                continue

            # Extract tvg-id and name from the #EXTINF line
            channel_id_match = re.search(r'tvg-id="([^"]*)"', line)

            channel_id_raw = channel_id_match.group(1) if channel_id_match else ""
            # Strip feed qualifier suffix: "ArubaTV.aw@SD" → "ArubaTV.aw"
            channel_id = channel_id_raw.split("@")[0]

            # Channel name follows the LAST comma on the #EXTINF line;
            # earlier commas may appear inside attribute values (e.g. user-agent).
            raw_name = line.rsplit(",", 1)[-1].strip() if "," in line else ""
            name = re.sub(r'\s*\(\d+(?:i|p)\)\s*', '', raw_name).strip()
            name = re.sub(r'\s*\[.*?\]\s*', '', name).strip()

            label_match = re.search(r'\[([^\]]+)\]', lines[i])
            label = label_match.group(1) if label_match else None

            # Skip #EXTVLCOPT lines to reach the URL
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("#"):
                j += 1

            url = lines[j].strip() if j < len(lines) else ""

            if url and not url.startswith("#"):
                channels.append({
                    "channel_id": channel_id,
                    "name": name,
                    "url": url,
                    "label": label,
                })

            i = j + 1

        return channels

    def get_travel_channels(self) -> list[dict]:
        """Fetch travel channels from iptv-org, applying banlist and allowlist.

        If an allowlist is present, only channels explicitly listed there are
        returned (after banlist exclusion). Allowlist metadata (country,
        legality_notes) is merged into each returned dict.

        Returns:
            List of dicts with keys: channel_id, name, url, label,
            and optionally country, legality_notes when allowlist is active.
        """
        resp = self._client.get(TRAVEL_M3U_URL)
        resp.raise_for_status()

        channels = self._parse_m3u(resp.text)
        before = len(channels)

        channels = [c for c in channels if c["channel_id"] not in self._banlist]
        banned_count = before - len(channels)
        if banned_count:
            logger.info(f"Filtered {banned_count} banned channel(s) from travel list")

        if self._allowlist is not None:
            allowed = []
            for c in channels:
                meta = self._allowlist.get(c["channel_id"])
                if meta:
                    allowed.append({**c, **{k: meta[k] for k in ("country", "legality_notes") if k in meta}})
            not_listed = len(channels) - len(allowed)
            if not_listed:
                logger.info(f"Skipped {not_listed} channel(s) not in allowlist")
            channels = allowed

        logger.info(f"Found {len(channels)} permitted travel channels")
        return channels
