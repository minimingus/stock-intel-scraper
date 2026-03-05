import logging
import signal
import sys

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler

from .brief import BriefGenerator
from .discovery import ExpertDiscovery
from .extractor import SignalExtractor
from .scraper import TwitterScraper
from .scorer import ExpertScorer
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
    scorer = ExpertScorer(store, lookback_hours=168)  # score signals from last 7 days
    brief = BriefGenerator(
        store,
        lookback_hours=intel_cfg.get("lookback_hours", 24),
        min_expert_mentions=intel_cfg.get("min_expert_mentions", 2),
        scorer=scorer,
    )
    return store, scraper, extractor, discovery, brief


def scrape_and_extract(store, scraper, extractor, discovery, cfg):
    handles = store.get_active_experts()
    logger.info("Scraping %d expert accounts...", len(handles))

    all_tweets = []
    for handle, tweets in scraper.scrape_all(handles).items():
        for t in tweets:
            store.insert_tweet(t["tweet_id"], handle, t["text"], t["likes"], t["retweets"], t.get("tweet_time"))
            all_tweets.append({"tweet_id": t["tweet_id"], "text": t["text"]})

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
