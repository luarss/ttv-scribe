"""Free proxy list fetching for CI (proxyscrape API)."""

import logging
import random
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

PROXYSCRAPE_URL = (
    "https://api.proxyscrape.com/v4/free-proxy-list/get"
    "?request=display_proxies&proxy_format=protocolipport&format=text"
    "&protocol=socks5&timeout=5000"
)


def fetch_proxies(limit: int = 15) -> list[str]:
    """Fetch fresh SOCKS5 proxies from proxyscrape, return shuffled list.

    Returns empty list if the fetch fails (caller should fall back to direct).
    """
    req = Request(PROXYSCRAPE_URL, headers={"User-Agent": "ttv-scribe/1.0"})
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
        proxies = [line.strip() for line in raw.splitlines() if line.strip()]
        random.shuffle(proxies)
        selected = proxies[:limit]
        logger.info(f"Fetched {len(proxies)} proxies, using {len(selected)}")
        return selected
    except Exception as e:
        logger.warning(f"Failed to fetch proxies: {e}")
        return []
