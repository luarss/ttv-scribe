"""Free proxy list fetching for CI (proxyscrape API)."""

import concurrent.futures
import logging
import random
import re
import socket
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

PROXYSCRAPE_URL = (
    "https://api.proxyscrape.com/v4/free-proxy-list/get"
    "?request=display_proxies&proxy_format=protocolipport&format=text"
    "&protocol=socks5&timeout=5000"
)

# IP prefixes known to be dead/unreachable — filtered out before shuffling.
DEFAULT_SKIP_PREFIXES: list[str] = ["138.199.", "142.54.", "167.71.", "184.170.", "206.123.", "68.71.", "85.155.", "192.111.", "192.252."]


def _extract_ip(proxy_url: str) -> str:
    """Extract the IP address from a proxy URL like socks5://1.2.3.4:port."""
    m = re.search(r"://([^:/]+)", proxy_url)
    return m.group(1) if m else ""


def _tcp_probe(proxy_url: str, timeout: float = 2.0) -> bool:
    """Return True if a TCP connection to *proxy_url* succeeds within *timeout*."""
    try:
        parsed = urlparse(proxy_url)
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            return False
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except Exception:
        return False


def _probe_all(proxies: list[str], timeout: float = 2.0) -> list[str]:
    """Probe every proxy in parallel; return only the reachable ones."""
    if not proxies:
        return []
    alive: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(50, len(proxies))) as ex:
        future_to_proxy = {ex.submit(_tcp_probe, p, timeout): p for p in proxies}
        for future in concurrent.futures.as_completed(future_to_proxy):
            if future.result():
                alive.append(future_to_proxy[future])
    return alive


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

        before_probe = len(proxies)
        proxies = _probe_all(proxies)
        dead = before_probe - len(proxies)
        if dead:
            logger.info(f"Probe filtered {dead} dead proxies, {len(proxies)} alive")

        random.shuffle(proxies)
        selected = proxies[:limit]
        logger.info(
            f"Fetched {len(proxies)} proxies (probed), using {len(selected)}"
        )
        return selected
    except Exception as e:
        logger.warning(f"Failed to fetch proxies: {e}")
        return []
