from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_COUNT = 100   # tweets per account for regular scrape
_BACKFILL_COUNT = 200  # tweets per account for backfill (user-tweets max is 200)
_DEEP_MONTHS = 3       # how far back deep_scrape goes


def _parse_created_at(s: str) -> Optional[str]:
    """Convert 'Thu Mar 05 21:21:04 +0000 2026' to ISO 8601 UTC string."""
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%a %b %d %H:%M:%S +0000 %Y")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def _bird_cmd() -> str:
    """Return path to bird Twitter CLI. Uses BIRD_BIN env var to avoid collision with
    the system 'bird' routing daemon present on Linux."""
    return os.environ.get("BIRD_BIN", "bird")


def _parse_tweets(raw: list) -> list:
    """Parse raw tweet dicts from bird JSON into our internal format."""
    tweets = []
    for t in raw:
        tweet_id = str(t.get("id", ""))
        text = t.get("text", "")
        if text.startswith("RT @"):
            continue
        if not tweet_id or not text:
            continue
        tweets.append({
            "tweet_id": tweet_id,
            "text": text,
            "likes": t.get("likeCount", 0) or 0,
            "retweets": t.get("retweetCount", 0) or 0,
            "tweet_time": _parse_created_at(t.get("createdAt")),
            "author_id": str(t.get("authorId", "")),
        })
    return tweets


def _run_user_tweets(handle: str, cursor: str = None) -> "tuple[list, Optional[str]]":
    """
    Run one page-batch of bird user-tweets (up to 200 tweets, 10 pages).
    Returns (tweets, next_cursor). next_cursor is None if no more pages.
    """
    cmd = [_bird_cmd(), "user-tweets", handle, "-n", "200", "--max-pages", "10", "--json"]
    if cursor:
        cmd += ["--cursor", cursor]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=180, env=os.environ.copy())
        if result.returncode != 0:
            logger.warning("bird user-tweets failed for @%s: %s", handle, result.stderr.strip()[:120])
            return [], None

        out = result.stdout
        # Output format: info lines then a JSON array
        arr_start = out.find("[")
        obj_start = out.find("{")
        next_cursor = None
        raw = []

        if obj_start != -1 and (arr_start == -1 or obj_start < arr_start):
            data = json.loads(out[obj_start:])
            raw = data.get("tweets", [])
            next_cursor = data.get("nextCursor")
        elif arr_start != -1:
            raw = json.loads(out[arr_start:])
            # cursor may appear after the array
            cursor_marker = '"nextCursor"'
            ci = out.find(cursor_marker, arr_start)
            if ci != -1:
                snippet = out[ci + len(cursor_marker):ci + len(cursor_marker) + 100]
                import re
                m = re.search(r':\s*"([^"]+)"', snippet)
                if m:
                    next_cursor = m.group(1)

        return _parse_tweets(raw), next_cursor

    except subprocess.TimeoutExpired:
        logger.warning("bird user-tweets timed out for @%s", handle)
        return [], None
    except Exception as e:
        logger.warning("Error in user-tweets for @%s: %s", handle, e)
        return [], None


def deep_scrape_handle(handle: str, months_back: int = _DEEP_MONTHS) -> list:
    """
    Fetch all tweets for handle going back `months_back` months using cursor pagination.
    Stops when oldest tweet in a batch predates the cutoff, or no more pages.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=months_back * 30)
    cutoff_str = cutoff.isoformat()

    all_tweets: list = []
    seen_ids: set = set()
    cursor = None
    iteration = 0
    max_iterations = 30  # safety: 30 × 200 = 6000 tweets max

    logger.info("Deep scraping @%s (cutoff %s)...", handle, cutoff_str[:10])

    while iteration < max_iterations:
        batch, next_cursor = _run_user_tweets(handle, cursor)
        iteration += 1

        if not batch:
            break

        new = [t for t in batch if t["tweet_id"] not in seen_ids]
        for t in new:
            seen_ids.add(t["tweet_id"])
        all_tweets.extend(new)

        # Check if we've gone back far enough
        times = [t["tweet_time"] for t in batch if t["tweet_time"]]
        if times and min(times) < cutoff_str:
            break  # oldest tweet in this batch is before cutoff

        if not next_cursor:
            break

        cursor = next_cursor
        time.sleep(1.5)  # rate-limit friendly delay between pages

    # Trim to cutoff window and drop tweets with implausible dates (>10 years ago)
    floor = (datetime.now(timezone.utc) - timedelta(days=365 * 10)).isoformat()
    result = [
        t for t in all_tweets
        if t["tweet_time"] and t["tweet_time"] >= cutoff_str
        and t["tweet_time"] >= floor
    ]
    logger.info("Deep scrape @%s: %d tweets in window (total fetched: %d)",
                handle, len(result), len(all_tweets))
    return result


def get_following(user_id: str, max_count: int = 200) -> list:
    """
    Return list of accounts that user_id follows.
    Each dict has: id, username, name, description.
    """
    cmd = [_bird_cmd(), "following", "--user", user_id,
           "-n", str(min(max_count, 200)), "--json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=60, env=os.environ.copy())
        if result.returncode != 0:
            logger.warning("bird following failed for %s: %s", user_id, result.stderr.strip()[:120])
            return []

        out = result.stdout
        arr_start = out.find("[")
        if arr_start == -1:
            return []
        raw = json.loads(out[arr_start:])
        return [
            {
                "id": str(u.get("id", u.get("userId", ""))),
                "username": u.get("username") or u.get("screenName", ""),
                "name": u.get("name", ""),
                "description": u.get("description", "") or "",
            }
            for u in raw
            if u.get("username") or u.get("screenName")
        ]
    except Exception as e:
        logger.warning("Error getting following for %s: %s", user_id, e)
        return []


def _fetch_tweets_search(handle: str, count: int) -> list:
    """Fallback: fetch tweets via bird search 'from:handle'."""
    try:
        result = subprocess.run(
            [_bird_cmd(), "search", f"from:{handle}", "-n", str(count), "--json", "--plain"],
            capture_output=True,
            text=True,
            timeout=60,
            env=os.environ.copy(),
        )
        if result.returncode != 0:
            logger.warning("bird failed for @%s: %s", handle, result.stderr.strip())
            return []

        out = result.stdout
        json_start = out.find("[")
        if json_start == -1:
            return []

        return _parse_tweets(json.loads(out[json_start:]))
    except subprocess.TimeoutExpired:
        logger.warning("bird timed out for @%s", handle)
        return []
    except Exception as e:
        logger.warning("Error fetching @%s: %s", handle, e)
        return []


def _fetch_tweets(handle: str, count: int) -> list:
    """Fetch tweets — uses user-tweets timeline (better history than search)."""
    batch, _ = _run_user_tweets(handle)
    if batch:
        return batch
    return _fetch_tweets_search(handle, count)


class TwitterScraper:
    def scrape_handle(self, handle: str, scroll_rounds: int = 0) -> list:
        """
        Fetch tweets for a handle via bird CLI.
        scroll_rounds is ignored (kept for API compatibility) — use count instead.
        Backfill uses _BACKFILL_COUNT; regular uses _DEFAULT_COUNT.
        """
        count = _BACKFILL_COUNT if scroll_rounds > 8 else _DEFAULT_COUNT
        return _fetch_tweets(handle, count)

    def scrape_all(self, handles: list, delay_ms: int = 3000) -> dict:
        """Scrape multiple handles with a delay to avoid rate limiting."""
        results = {}
        for i, handle in enumerate(handles):
            results[handle] = self.scrape_handle(handle)
            logger.info("Scraped @%s: %d tweets", handle, len(results[handle]))
            if i < len(handles) - 1:
                time.sleep(delay_ms / 1000)
        return results
