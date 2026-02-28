import logging
import os
from datetime import datetime, timezone, timedelta

import yaml
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
from anthropic import Anthropic

from src.twitter.fetcher import TweetFetcher
from src.twitter.filter import RelevanceFilter
from src.twitter.synthesizer import Synthesizer
from src.twitter.signal_store import SignalStore
from src.twitter.notifier import TelegramNotifier

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _load_config() -> dict:
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def scan_cycle() -> None:
    cfg = _load_config()
    tw = cfg.get("twitter", {})

    store = SignalStore()
    fetcher = TweetFetcher(
        username=os.environ["TWITTER_USERNAME"],
        password=os.environ["TWITTER_PASSWORD"],
        email=os.environ["TWITTER_EMAIL"],
    )
    filt = RelevanceFilter(
        min_engagement=tw.get("min_engagement", 5),
        keywords=tw.get("keywords_boost"),
    )
    synth = Synthesizer()
    notifier = TelegramNotifier()

    accounts = tw.get("accounts", [])
    since_hours = tw.get("scan_interval_hours", 4)
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(hours=since_hours)

    log.info("Scan cycle: %d accounts, window=%dh", len(accounts), since_hours)
    tweets = fetcher.fetch(accounts, since_hours=since_hours, store=store)
    log.info("Fetched %d new tweets", len(tweets))

    filtered = filt.filter(tweets)
    log.info("Filtered to %d relevant tweets", len(filtered))

    signals = synth.synthesize(filtered)
    log.info("Synthesized %d topic signals", len(signals))

    for sig in signals:
        store.append_signal(
            topic=sig["topic"],
            summary=sig["summary"],
            sources=[tw_["url"] for tw_ in sig.get("tweets", [])],
            relevance_score=1.0,
        )

    store.prune_old(days=7)
    notifier.send_digest(signals, window_start, window_end)


def daily_brief() -> None:
    cfg = _load_config()
    lookback = cfg.get("signal_feed", {}).get("lookback_hours", 24)

    store = SignalStore()
    notifier = TelegramNotifier()
    signals = store.get_signals_since(hours=lookback)

    if not signals:
        log.info("No signals in last %dh — skipping daily brief", lookback)
        return

    summary_text = "\n".join(f"- {s['topic']}: {s['summary']}" for s in signals)
    client = Anthropic()
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": (
                "Write a concise 'what mattered today in AI' narrative "
                "(4-6 sentences) based on these signals:\n" + summary_text
            ),
        }],
    )
    narrative = response.content[0].text.strip()
    notifier.send_daily_brief(narrative, datetime.now(timezone.utc))


def main() -> None:
    cfg = _load_config()
    tw = cfg.get("twitter", {})
    interval_hours = tw.get("scan_interval_hours", 4)
    brief_hour = tw.get("daily_brief_hour_utc", 9)

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(scan_cycle, "interval", hours=interval_hours, id="scan")
    scheduler.add_job(daily_brief, "cron", hour=brief_hour, id="daily_brief")
    log.info(
        "Scanner starting: every %dh + daily brief at %02d:00 UTC",
        interval_hours, brief_hour,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
