"""IPTV channel recording state — round-robin rotation based on last_recorded_at."""

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_EPOCH = "1970-01-01T00:00:00Z"
_STATE_FILE = "iptv_state.json"


def load_state(state_dir: str) -> dict:
    path = os.path.join(state_dir, _STATE_FILE)
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"channels": {}}


def save_state(state: dict, state_dir: str):
    path = os.path.join(state_dir, _STATE_FILE)
    with open(path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved IPTV channel state: {path}")


def sort_by_rotation(channels: list[dict], state: dict) -> list[dict]:
    """Sort channels oldest-last-recorded first for fair round-robin rotation.

    Channels never recorded are treated as recorded at epoch and sort first.
    """
    ch_state = state.get("channels", {})

    def _last_recorded(ch: dict) -> str:
        return ch_state.get(ch["channel_id"], {}).get("last_recorded_at", _EPOCH)

    return sorted(channels, key=_last_recorded)


def mark_recorded(channel_id: str, state: dict) -> dict:
    """Set last_recorded_at to now for the given channel."""
    state.setdefault("channels", {})[channel_id] = {
        "last_recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    return state
