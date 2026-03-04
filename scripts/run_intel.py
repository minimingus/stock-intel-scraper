#!/usr/bin/env -S .venv/bin/python3
"""
Manual trigger for Twitter Intel.

Usage:
    python scripts/run_intel.py scrape    # scrape + extract signals now
    python scripts/run_intel.py brief     # generate + send brief now
    python scripts/run_intel.py start     # start the scheduler (blocking)
"""
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
sys.path.insert(0, ".")

from src.twitter_intel import scheduler as sched


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    cfg = sched.load_config()

    if cmd == "start":
        # run() handles its own component lifecycle
        sched.run()
        return

    store, scraper, extractor, discovery, brief = sched.build_components(cfg)
    try:
        if cmd == "scrape":
            sched.scrape_and_extract(store, scraper, extractor, discovery, cfg)
        elif cmd == "brief":
            brief.send()
        else:
            print(f"Unknown command: {cmd}")
            print(__doc__)
            sys.exit(1)
    finally:
        store.close()


if __name__ == "__main__":
    main()
