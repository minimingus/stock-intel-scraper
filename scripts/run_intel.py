#!/usr/bin/env -S .venv/bin/python3
"""
Manual trigger for Twitter Intel.

Usage:
    python scripts/run_intel.py scrape                          # scrape + extract signals now
    python scripts/run_intel.py brief                           # generate + send brief now
    python scripts/run_intel.py start                           # start the scheduler (blocking)
    python scripts/run_intel.py backfill                        # deep-scrape all new experts
    python scripts/run_intel.py backfill handle1,handle2        # deep-scrape specific handles
    python scripts/run_intel.py deep_backfill handle1,handle2   # 3-month cursor pagination
    python scripts/run_intel.py prune                           # deactivate underperformers
    python scripts/run_intel.py discover handle1,handle2        # discover experts via following
    python scripts/run_intel.py alert                           # run alert check and send alerts
"""
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)
sys.path.insert(0, ".")

from src.twitter_intel import scheduler as sched
from src.twitter_intel import alerter as alert_module
from src.twitter_intel.scorer import ExpertScorer


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    cfg = sched.load_config()

    if cmd == "start":
        sched.run()
        return

    store, scraper, extractor, discovery, brief = sched.build_components(cfg)
    try:
        if cmd == "scrape":
            sched.scrape_and_extract(store, scraper, extractor, discovery, cfg)
        elif cmd == "brief":
            brief.send()
        elif cmd == "backfill":
            handles = None
            if len(sys.argv) > 2 and sys.argv[2]:
                handles = [h.strip() for h in sys.argv[2].split(",") if h.strip()]
            sched.backfill_experts(store, scraper, extractor, handles)
        elif cmd == "deep_backfill":
            handles = [h.strip() for h in sys.argv[2].split(",") if h.strip()] if len(sys.argv) > 2 else store.get_active_experts()
            sched.deep_backfill_experts(store, extractor, handles, months_back=3)
        elif cmd == "prune":
            deactivated = sched.prune_underperforming_experts(store)
            if deactivated:
                logger.info("Deactivated: %s", ", ".join(f"@{h}" for h in deactivated))
            else:
                logger.info("No experts pruned (none meet deactivation criteria yet)")
        elif cmd == "discover":
            handles = [h.strip() for h in sys.argv[2].split(",") if h.strip()] if len(sys.argv) > 2 else []
            if not handles:
                logger.error("discover requires comma-separated handles: discover handle1,handle2")
            else:
                added = sched.discover_from_following(store, handles)
                logger.info("Discovered %d new experts", added)
        elif cmd == "alert":
            scorer = ExpertScorer(store)
            sent = alert_module.run_alert_check(store, scorer)
            pump_sent = alert_module.run_penny_pump_check(store)
            logger.info("Alert check: %d convergence, %d pump alerts sent", sent, pump_sent)
        else:
            print(f"Unknown command: {cmd}")
            print(__doc__)
            sys.exit(1)
    finally:
        store.close()


if __name__ == "__main__":
    main()
