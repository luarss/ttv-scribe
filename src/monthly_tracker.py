"""Monthly usage tracker for transcription minutes"""

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings

logger = logging.getLogger(__name__)

# File to store monthly usage data
MONTHLY_USAGE_FILE = "state/monthly_usage.json"


def _get_usage_file_path() -> Path:
    """Get the path to the monthly usage file"""
    settings = get_settings()
    state_dir = Path(settings.state_file_dir)
    return state_dir / "monthly_usage.json"


def _load_usage() -> dict:
    """Load monthly usage from file"""
    usage_file = _get_usage_file_path()

    if usage_file.exists():
        try:
            with open(usage_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load monthly usage: {e}")

    return {"year": 0, "month": 0, "minutes_used": 0, "github_minutes_used": 0}


def _save_usage(usage: dict):
    """Save monthly usage to file"""
    usage_file = _get_usage_file_path()
    usage_file.parent.mkdir(parents=True, exist_ok=True)

    with open(usage_file, "w", encoding="utf-8") as f:
        json.dump(usage, f, indent=2, ensure_ascii=False)


def _get_current_month() -> tuple[int, int]:
    """Get current year and month (UTC)"""
    now = datetime.now(timezone.utc)
    return now.year, now.month


def check_month_rollover() -> bool:
    """Check if the month has rolled over and reset usage if needed

    Returns:
        True if usage was reset (new month), False otherwise
    """
    current_year, current_month = _get_current_month()
    usage = _load_usage()

    # Check if we're in a new month
    if usage["year"] != current_year or usage["month"] != current_month:
        # Reset for new month
        new_usage = {
            "year": current_year,
            "month": current_month,
            "minutes_used": 0,
            "github_minutes_used": 0,
        }
        _save_usage(new_usage)
        logger.info(
            f"New month detected ({current_year}-{current_month:02d}), resetting monthly usage"
        )
        return True

    return False


def get_remaining_minutes() -> int:
    """Get remaining GitHub Actions minutes for the current month

    Returns:
        Remaining minutes (can be negative if over limit)
    """
    check_month_rollover()

    settings = get_settings()
    usage = _load_usage()

    remaining = settings.monthly_minutes_limit - usage.get("github_minutes_used", 0)
    return max(remaining, 0)


def add_minutes_used(minutes: float):
    """Add minutes used to the monthly counter

    Args:
        minutes: Number of minutes to add
    """
    check_month_rollover()

    usage = _load_usage()
    usage["minutes_used"] += minutes

    logger.debug(
        f"Added {minutes:.2f} minutes to monthly usage (total: {usage['minutes_used']:.2f})"
    )
    _save_usage(usage)


def get_usage_info() -> dict:
    """Get current usage information

    Returns:
        Dict with year, month, minutes_used, and limit
    """
    check_month_rollover()

    settings = get_settings()
    usage = _load_usage()

    return {
        "year": usage["year"],
        "month": usage["month"],
        "minutes_used": usage["minutes_used"],
        "limit": settings.monthly_minutes_limit,
        "remaining": get_remaining_minutes(),
        "github_minutes_used": usage.get("github_minutes_used", 0),
    }


def fetch_github_actions_minutes() -> float:
    """Fetch GitHub Actions runner minutes from API for current month

    Returns:
        Total minutes used by successful workflow runs since start of month
    """
    from .config import get_settings

    settings = get_settings()

    try:
        # Get repo info from config or use default
        # Assuming format "owner/repo" or just use the repo from environment
        repo = getattr(settings, "github_repo", None)
        if not repo:
            # Try to get from gh CLI
            result = subprocess.run(
                [
                    "gh",
                    "repo",
                    "view",
                    "--json",
                    "owner,name",
                    "-q",
                    '.owner.login + "/" + .name',
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            repo = result.stdout.strip()

        if not repo:
            logger.warning("Could not determine GitHub repo forActions minutes")
            return 0

        owner, name = repo.split("/")

        # Get current month start date
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_start_str = month_start.strftime("%Y-%m-%d")

        # Query successful runs since start of month (with pagination for >30 runs)
        jq_filter = f'.workflow_runs[] | select(.created_at >= "{month_start_str}" and .conclusion == "success") | .id'
        cmd = [
            "gh",
            "api",
            f"repos/{owner}/{name}/actions/runs",
            "--paginate",
            "--jq",
            jq_filter,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        run_ids = result.stdout.strip().split("\n") if result.stdout.strip() else []

        if not run_ids:
            return 0

        total_seconds = 0
        for run_id in run_ids:
            if not run_id:
                continue

            # Get job timing info
            jobs_jq = '.jobs[] | "\\(.started_at)\\t\\(.completed_at)"'
            jobs_result = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{owner}/{name}/actions/runs/{run_id}/jobs",
                    "--jq",
                    jobs_jq,
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            if not jobs_result.stdout.strip():
                continue

            for line in jobs_result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) != 2:
                    continue
                start_str, end_str = parts

                # Parse timestamps
                start = datetime.strptime(start_str[:-1], "%Y-%m-%dT%H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
                end = datetime.strptime(end_str[:-1], "%Y-%m-%dT%H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
                total_seconds += (end - start).total_seconds()

        minutes = total_seconds / 60
        logger.info(f"GitHub Actions minutes since {month_start_str}: {minutes:.2f}")
        return minutes

    except subprocess.CalledProcessError as e:
        logger.warning(f"Failed to fetch GitHub Actions minutes: {e}")
        return 0
    except Exception as e:
        logger.warning(f"Error fetching GitHub Actions minutes: {e}")
        return 0


def update_github_minutes():
    """Fetch and store GitHub Actions runner minutes"""
    check_month_rollover()

    minutes = fetch_github_actions_minutes()

    usage = _load_usage()
    usage["github_minutes_used"] = round(minutes, 2)

    logger.debug(f"Updated GitHub Actions minutes: {usage['github_minutes_used']:.2f}")
    _save_usage(usage)
