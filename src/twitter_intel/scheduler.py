from __future__ import annotations

import logging
import re
import signal
import sys

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler

from .brief import BriefGenerator
from .discovery import ExpertDiscovery
from .extractor import SignalExtractor
from .scraper import TwitterScraper, deep_scrape_handle, get_following
from .store import TwitterIntelStore

logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_components(cfg: dict):
    intel_cfg = cfg.get("twitter_intel", {})
    store = TwitterIntelStore()

    for handle in intel_cfg.get("seed_accounts", []):
        store.upsert_expert(handle, source="seed")

    scraper = TwitterScraper()
    extractor = SignalExtractor(store)
    discovery = ExpertDiscovery(
        store,
        max_accounts=intel_cfg.get("auto_expand", {}).get("max_accounts", 100),
        min_interactions=intel_cfg.get("auto_expand", {}).get("min_interactions", 3),
    )
    brief = BriefGenerator(
        store,
        lookback_hours=intel_cfg.get("lookback_hours", 48),
    )
    return store, scraper, extractor, discovery, brief


_BACKFILL_SCROLL_ROUNDS = 20  # deep scrape for backfill (~150-200 tweets)


def _ingest_tweets(store, handle: str, tweets: list, all_tweets: list):
    for t in tweets:
        store.insert_tweet(
            t["tweet_id"], handle, t["text"],
            t["likes"], t["retweets"], t.get("tweet_time"),
        )
        all_tweets.append({"tweet_id": t["tweet_id"], "text": t["text"]})


def deep_backfill_experts(store, extractor, handles: list, months_back: int = 3):
    """
    Deep-scrape handles using cursor pagination going back `months_back` months.
    Also saves author_ids for discovery.
    """
    logger.info("Deep backfill: %d expert(s), %d months back", len(handles), months_back)
    all_tweets = []
    for handle in handles:
        tweets = deep_scrape_handle(handle, months_back=months_back)
        for t in tweets:
            store.insert_tweet(
                t["tweet_id"], handle, t["text"],
                t["likes"], t["retweets"], t.get("tweet_time"),
            )
            # Save author_id for later following-based discovery
            if t.get("author_id"):
                store.set_author_id(handle, t["author_id"])
        all_tweets.extend(tweets)
        logger.info("Deep backfill @%s: %d tweets in window", handle, len(tweets))

    count = extractor.run()
    logger.info("Extracted %d signals from deep backfill", count)


def prune_underperforming_experts(store, min_trades: int = 10,
                                   max_win_rate: float = 0.40) -> list[str]:
    """
    Deactivate experts with ≥ min_trades closed trades AND win_rate < max_win_rate
    AND negative expectancy. Returns list of deactivated handles.
    """
    from .scorer import ExpertScorer
    scores = ExpertScorer(store).score()
    deactivated = []
    for e in scores:
        if e["total"] >= min_trades and e["win_rate"] < max_win_rate and e["expectancy"] <= 0:
            store.deactivate_expert(e["handle"])
            deactivated.append(e["handle"])
            logger.info("Deactivated underperformer @%s (%.0f%% win, E=%.2f%%, %d trades)",
                        e["handle"], e["win_rate"] * 100, e["expectancy"] * 100, e["total"])
    return deactivated


# Stock-focused keywords to filter discovered accounts
_STOCK_KEYWORDS = re.compile(
    r"\b(trade[r]?s?|stock|invest|market|options|swing|daytr|momentum|"
    r"chart|technical|analysis|bull|bear|penny|small.?cap|nasdaq|nyse|"
    r"hedge|fund|portfolio|equity|capital|alert|picks?|signals?)\b",
    re.IGNORECASE,
)


def discover_from_following(store, top_handles: list[str],
                             max_per_expert: int = 200) -> int:
    """
    For each top expert, fetch who they follow and add stock-focused accounts
    as new experts. Returns count of new experts added.
    """
    # Build handle→author_id map from DB
    known = {r["handle"]: r["author_id"] for r in store.get_experts_with_author_ids()}
    existing_handles = {h.lower() for h in store.get_active_experts()}
    added = 0

    for handle in top_handles:
        author_id = known.get(handle)
        if not author_id:
            logger.warning("No author_id for @%s — cannot fetch following", handle)
            continue

        logger.info("Fetching following for @%s (id=%s)...", handle, author_id)
        following = get_following(author_id, max_count=max_per_expert)
        logger.info("@%s follows %d accounts", handle, len(following))

        for user in following:
            uname = user.get("username", "").strip()
            if not uname or uname.lower() in existing_handles:
                continue
            bio = user.get("description", "")
            if _STOCK_KEYWORDS.search(bio):
                store.upsert_expert(uname, source="following")
                existing_handles.add(uname.lower())
                added += 1
                logger.info("  Added @%s from @%s's following (bio: %s)",
                            uname, handle, bio[:60])

    logger.info("discover_from_following: added %d new experts", added)
    return added


def backfill_experts(store, scraper, extractor, handles: list = None):
    """Deep-scrape specific handles (or all new experts) for backtesting."""
    targets = handles or store.get_experts_without_tweets()
    if not targets:
        logger.info("No experts to backfill")
        return
    logger.info("Backfilling %d expert(s) with %d scroll rounds each...",
                len(targets), _BACKFILL_SCROLL_ROUNDS)
    for handle in targets:
        tweets = scraper.scrape_handle(handle, scroll_rounds=_BACKFILL_SCROLL_ROUNDS)
        _ingest_tweets(store, handle, tweets, [])
        logger.info("Backfilled @%s: %d tweets", handle, len(tweets))
    count = extractor.run()
    logger.info("Extracted %d signals from backfill", count)


def scrape_top_experts(store, scraper, extractor, discovery, cfg, top_n: int = 5):
    """Fast-poll: scrape only top N qualified experts by adjusted_expectancy."""
    from .scorer import ExpertScorer
    scores = ExpertScorer(store).score()
    qualified = [
        e["handle"] for e in scores
        if e["total"] >= 5 and e.get("expectancy", 0) > 0
    ][:top_n]
    if not qualified:
        logger.debug("Fast-poll: no qualified experts yet, skipping")
        return
    logger.info("Fast-poll: scraping top %d experts: %s", len(qualified), qualified)
    for handle, tweets in scraper.scrape_all(qualified).items():
        _ingest_tweets(store, handle, tweets, [])
    count = extractor.run()
    if count:
        logger.info("Fast-poll extracted %d signals", count)


def scrape_and_extract(store, scraper, extractor, discovery, cfg):
    all_tweets = []

    # Regular scrape for all active experts
    handles = store.get_active_experts()
    logger.info("Scraping %d expert accounts...", len(handles))
    for handle, tweets in scraper.scrape_all(handles).items():
        _ingest_tweets(store, handle, tweets, all_tweets)

    count = extractor.run()
    logger.info("Extracted %d signals", count)

    if cfg.get("twitter_intel", {}).get("auto_expand", {}).get("enabled", True):
        added = discovery.run(all_tweets)
        if added:
            logger.info("Added %d experts via auto-discovery", added)


def run(config_path: str = "config.yaml"):
    cfg = load_config(config_path)
    intel_cfg = cfg.get("twitter_intel", {})
    store, scraper, extractor, discovery, brief = build_components(cfg)

    interval_hours = intel_cfg.get("scrape_interval_hours", 4)
    brief_time = intel_cfg.get("brief_time", "08:00")
    try:
        brief_hour, brief_minute = map(int, brief_time.split(":"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(
            f"twitter_intel.brief_time must be in HH:MM format, got: {brief_time!r}"
        ) from exc

    scheduler = BlockingScheduler()

    scheduler.add_job(
        scrape_and_extract,
        "interval",
        hours=interval_hours,
        args=[store, scraper, extractor, discovery, cfg],
        id="scrape",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        brief.send,
        "cron",
        hour=brief_hour,
        minute=brief_minute,
        id="brief",
    )
    scheduler.add_job(
        scrape_top_experts,
        "interval",
        minutes=30,
        args=[store, scraper, extractor, discovery, cfg],
        id="fast_poll",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        store.prune_old_tweets,
        "cron",
        hour=2,
        minute=0,
        id="prune",
    )

    logger.info(
        "Twitter Intel started. Brief at %s, scraping every %dh.",
        brief_time,
        interval_hours,
    )

    def _shutdown(signum, frame):
        logger.info("Received signal %d, shutting down...", signum)
        scheduler.shutdown(wait=True)
        store.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Immediate first scrape on startup
    scrape_and_extract(store, scraper, extractor, discovery, cfg)
    scheduler.start()
