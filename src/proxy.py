"""Free proxy list fetching for CI (proxyscrape API + GitHub fallback)."""

import concurrent.futures
import logging
import random
import re
import socket
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_PROXYSCRAPE_BASE = (
    "https://api.proxyscrape.com/v4/free-proxy-list/get"
    "?request=display_proxies&proxy_format=protocolipport&format=text"
)

PROXYSCRAPE_HTTP_URL = f"{_PROXYSCRAPE_BASE}&protocol=http&timeout=5000"
PROXYSCRAPE_SOCKS5_URL = f"{_PROXYSCRAPE_BASE}&protocol=socks5&timeout=5000"

GITHUB_HTTP_URL = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
GITHUB_SOCKS5_URL = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt"

DEFAULT_LIMIT = 25
DEFAULT_GITHUB_MAX_LINES = 200

# IP prefixes known to be dead/unreachable — filtered out before probing.
DEFAULT_SKIP_PREFIXES: list[str] = [
    "138.199.", "142.54.", "167.71.", "184.170.", "206.123.",
    "68.71.", "85.155.", "192.111.", "192.252.",
]


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


def _fetch_text(url: str, timeout: float = 10.0) -> str | None:
    """Fetch a URL and return decoded text, or None on failure."""
    try:
        req = Request(url, headers={"User-Agent": "ttv-scribe/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


def _parse_raw_host_port(
    text: str, scheme: str, max_lines: int = DEFAULT_GITHUB_MAX_LINES
) -> list[str]:
    """Parse bare ip:port lines and prefix them with *scheme*://."""
    proxies: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$", line):
            proxies.append(f"{scheme}://{line}")
            if len(proxies) >= max_lines:
                break
    return proxies


def _deduplicate_by_ip(proxies: list[str]) -> list[str]:
    """Keep only the first occurrence of each IP address."""
    seen: set[str] = set()
    unique: list[str] = []
    for p in proxies:
        ip = _extract_ip(p)
        if ip and ip not in seen:
            seen.add(ip)
            unique.append(p)
    return unique


def fetch_proxies(
    limit: int = DEFAULT_LIMIT,
    skip_prefixes: list[str] | None = None,
) -> list[str]:
    """Fetch fresh proxies from multiple sources, return shuffled list.

    Sources: proxyscrape (HTTP + SOCKS5), TheSpeedX/PROXY-List (HTTP + SOCKS5).
    Each source is fetched independently — one failing doesn't block others.

    Args:
        limit: Max proxies to return.
        skip_prefixes: IP prefixes to exclude (e.g. ``["206.123."]``).
                       Merged with :data:`DEFAULT_SKIP_PREFIXES`.

    Returns empty list if all sources fail (caller should fall back to direct).
    """
    if skip_prefixes is None:
        skip_prefixes = []
    all_skip = list(set(DEFAULT_SKIP_PREFIXES + skip_prefixes))

    proxies: list[str] = []

    # --- proxyscrape sources (scheme already in URL) ---
    for url in (PROXYSCRAPE_HTTP_URL, PROXYSCRAPE_SOCKS5_URL):
        text = _fetch_text(url)
        if text:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            proxies.extend(lines)
            logger.debug(f"Fetched {len(lines)} proxies from {url[:60]}...")

    # --- GitHub sources (bare ip:port, need scheme prefix) ---
    for url, scheme in ((GITHUB_HTTP_URL, "http"), (GITHUB_SOCKS5_URL, "socks5")):
        text = _fetch_text(url)
        if text:
            parsed = _parse_raw_host_port(text, scheme)
            proxies.extend(parsed)
            logger.debug(f"Fetched {len(parsed)} proxies from {url[:60]}...")

    if not proxies:
        logger.warning("No proxies fetched from any source")
        return []

    # --- Deduplicate by IP ---
    before_dedup = len(proxies)
    proxies = _deduplicate_by_ip(proxies)
    dupes = before_dedup - len(proxies)
    if dupes:
        logger.info(f"Deduplicated {dupes} duplicate IPs, {len(proxies)} unique")

    # --- Prefix blacklist ---
    if all_skip:
        before = len(proxies)
        proxies = [
            p for p in proxies
            if not any(_extract_ip(p).startswith(prefix) for prefix in all_skip)
        ]
        skipped = before - len(proxies)
        if skipped:
            logger.info(f"Filtered {skipped} proxies by IP prefix")

    # --- TCP probe ---
    before_probe = len(proxies)
    proxies = _probe_all(proxies)
    dead = before_probe - len(proxies)
    if dead:
        logger.info(f"Probe filtered {dead} dead proxies, {len(proxies)} alive")

    # --- Shuffle and limit ---
    random.shuffle(proxies)
    selected = proxies[:limit]
    logger.info(
        f"Returning {len(selected)} proxies (limit={limit}) "
        f"from {len(proxies)} alive after probing"
    )
    return selected
