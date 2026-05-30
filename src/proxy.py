"""Free proxy list fetching for CI (proxyscrape API)."""

import logging
import random
import re
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

PROXYSCRAPE_URL = (
    "https://api.proxyscrape.com/v4/free-proxy-list/get"
    "?request=display_proxies&proxy_format=protocolipport&format=text"
    "&protocol=socks5&timeout=5000"
)

# IP prefixes known to be dead/unreachable — filtered out before shuffling.
DEFAULT_SKIP_PREFIXES: list[str] = ["184.170.", "206.123.", "68.71.", "192.111.", "192.252."]


def _extract_ip(proxy_url: str) -> str:
    """Extract the IP address from a proxy URL like socks5://1.2.3.4:port."""
    m = re.search(r"://([^:/]+)", proxy_url)
    return m.group(1) if m else ""


def fetch_proxies(
    limit: int = 15,
    skip_prefixes: list[str] | None = None,
) -> list[str]:
    """Fetch fresh SOCKS5 proxies from proxyscrape, return shuffled list.

    Args:
        limit: Max proxies to return.
        skip_prefixes: IP prefixes to exclude (e.g. ``["206.123."]``).
                       Merged with :data:`DEFAULT_SKIP_PREFIXES`.

    Returns empty list if the fetch fails (caller should fall back to direct).
    """
    if skip_prefixes is None:
        skip_prefixes = []
    all_skip = list(set(DEFAULT_SKIP_PREFIXES + skip_prefixes))

    req = Request(PROXYSCRAPE_URL, headers={"User-Agent": "ttv-scribe/1.0"})
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
        proxies = [line.strip() for line in raw.splitlines() if line.strip()]

        if all_skip:
            before = len(proxies)
            proxies = [
                p for p in proxies
                if not any(_extract_ip(p).startswith(prefix) for prefix in all_skip)
            ]
            skipped = before - len(proxies)
            if skipped:
                logger.info(f"Filtered {skipped} proxies by IP prefix")

        random.shuffle(proxies)
        selected = proxies[:limit]
        logger.info(
            f"Fetched {len(proxies)} proxies (filtered), using {len(selected)}"
        )
        return selected
    except Exception as e:
        logger.warning(f"Failed to fetch proxies: {e}")
        return []
