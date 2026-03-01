import logging
import re
from collections import Counter

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)


class ExpertDiscovery:
    def __init__(self, store: TwitterIntelStore, max_accounts: int = 100, min_interactions: int = 3):
        self.store = store
        self.max_accounts = max_accounts
        self.min_interactions = min_interactions

    def discover_from_tweets(self, tweets: list) -> list:
        """Find @handles that appear >= min_interactions times and aren't already tracked."""
        existing = {h.lower() for h in self.store.get_active_experts()}
        current_count = len(existing)

        mention_counts: Counter = Counter()
        for tweet in tweets:
            for handle in re.findall(r"@(\w+)", tweet.get("text", "")):
                if handle.lower() not in existing:
                    mention_counts[handle.lower()] += 1

        new_handles = []
        for handle, count in mention_counts.most_common():
            if current_count >= self.max_accounts:
                break
            if count >= self.min_interactions:
                new_handles.append(handle)
                current_count += 1
        return new_handles

    def run(self, recent_tweets: list) -> int:
        """Discover and persist new experts. Returns count added."""
        new_handles = self.discover_from_tweets(recent_tweets)
        for handle in new_handles:
            self.store.upsert_expert(handle, source="discovered")
            logger.info("Discovered new expert: @%s", handle)
        return len(new_handles)
