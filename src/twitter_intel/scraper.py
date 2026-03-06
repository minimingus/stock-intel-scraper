import json
import logging
import os
import subprocess
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DEFAULT_COUNT = 100   # tweets per account for regular scrape
_BACKFILL_COUNT = 500  # tweets per account for backfill


def _parse_created_at(s: str) -> str | None:
    """Convert 'Thu Mar 05 21:21:04 +0000 2026' to ISO 8601 UTC string."""
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%a %b %d %H:%M:%S +0000 %Y")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def _bird_env() -> dict:
    env = os.environ.copy()
    # Ensure AUTH_TOKEN and CT0 are available
    return env


def _fetch_tweets(handle: str, count: int) -> list:
    """Call bird user-tweets and return parsed tweet dicts."""
    try:
        result = subprocess.run(
            ["bird", "user-tweets", handle, "-n", str(count), "--json", "--plain"],
            capture_output=True,
            text=True,
            timeout=60,
            env=_bird_env(),
        )
        if result.returncode != 0:
            logger.warning("bird failed for @%s: %s", handle, result.stderr.strip())
            return []

        # Output starts with info lines before JSON array — find the JSON
        out = result.stdout
        json_start = out.find("[")
        if json_start == -1:
            logger.warning("No JSON in bird output for @%s", handle)
            return []

        tweets_raw = json.loads(out[json_start:])
        tweets = []
        for t in tweets_raw:
            tweet_id = str(t.get("id", ""))
            text = t.get("text", "")
            if not tweet_id or not text:
                continue
            tweets.append({
                "tweet_id": tweet_id,
                "text": text,
                "likes": t.get("likeCount", 0) or 0,
                "retweets": t.get("retweetCount", 0) or 0,
                "tweet_time": _parse_created_at(t.get("createdAt")),
            })
        return tweets
    except subprocess.TimeoutExpired:
        logger.warning("bird timed out for @%s", handle)
        return []
    except Exception as e:
        logger.warning("Error fetching @%s: %s", handle, e)
        return []


class TwitterScraper:
    def scrape_handle(self, handle: str, scroll_rounds: int = 0) -> list:
        """
        Fetch tweets for a handle via bird CLI.
        scroll_rounds is ignored (kept for API compatibility) — use count instead.
        Backfill uses _BACKFILL_COUNT; regular uses _DEFAULT_COUNT.
        """
        count = _BACKFILL_COUNT if scroll_rounds > 8 else _DEFAULT_COUNT
        return _fetch_tweets(handle, count)

    def scrape_all(self, handles: list, delay_ms: int = 1000) -> dict:
        """Scrape multiple handles with a delay to avoid rate limiting."""
        import time
        results = {}
        for i, handle in enumerate(handles):
            results[handle] = self.scrape_handle(handle)
            logger.info("Scraped @%s: %d tweets", handle, len(results[handle]))
            if i < len(handles) - 1:
                time.sleep(delay_ms / 1000)
        return results
