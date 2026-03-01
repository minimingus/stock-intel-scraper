import pytest
from src.twitter_intel.discovery import ExpertDiscovery
from src.twitter_intel.store import TwitterIntelStore


@pytest.fixture
def store(tmp_path):
    s = TwitterIntelStore(db_path=str(tmp_path / "test.db"))
    s.upsert_expert("seed1", source="seed")
    return s


def test_discover_finds_frequently_mentioned_handle(store):
    tweets = [
        {"tweet_id": f"t{i}", "text": "@newtrader bullish on BTC"} for i in range(3)
    ]
    discovery = ExpertDiscovery(store, max_accounts=100, min_interactions=3)
    new = discovery.discover_from_tweets(tweets)
    assert "newtrader" in new


def test_discover_ignores_below_threshold(store):
    tweets = [
        {"tweet_id": "t1", "text": "@rarehandle only mentioned once"}
    ]
    discovery = ExpertDiscovery(store, max_accounts=100, min_interactions=3)
    new = discovery.discover_from_tweets(tweets)
    assert "rarehandle" not in new


def test_discover_ignores_existing_experts(store):
    tweets = [
        {"tweet_id": f"t{i}", "text": "@seed1 great call"} for i in range(5)
    ]
    discovery = ExpertDiscovery(store, max_accounts=100, min_interactions=3)
    new = discovery.discover_from_tweets(tweets)
    assert "seed1" not in new


def test_discover_respects_max_accounts(store):
    # store already has 1 expert; max_accounts=1 -> no room for new ones
    tweets = [
        {"tweet_id": f"t{i}", "text": "@newguy hot take"} for i in range(5)
    ]
    discovery = ExpertDiscovery(store, max_accounts=1, min_interactions=1)
    new = discovery.discover_from_tweets(tweets)
    assert len(new) == 0


def test_run_adds_discovered_experts_to_store(store):
    tweets = [
        {"tweet_id": f"t{i}", "text": "@discovered_expert signal"} for i in range(3)
    ]
    discovery = ExpertDiscovery(store, max_accounts=100, min_interactions=3)
    added = discovery.run(tweets)
    assert added == 1
    assert "discovered_expert" in store.get_active_experts()


def test_discover_counts_handle_once_per_tweet(store):
    """A handle mentioned 3 times in one tweet should count as 1, not 3."""
    tweets = [
        {"tweet_id": "t1", "text": "@newexpert @newexpert @newexpert mentioned thrice"},
    ]
    discovery = ExpertDiscovery(store, max_accounts=100, min_interactions=2)
    new = discovery.discover_from_tweets(tweets)
    # count is 1 (one tweet), threshold is 2 => should NOT be discovered
    assert "newexpert" not in new


def test_discover_handles_with_underscores_and_digits(store):
    """Regex must match real-world handles like @CryptoCapo_ and @tier10k."""
    tweets = [
        {"tweet_id": f"t{i}", "text": "@CryptoCapo_ and @tier10k are bullish"} for i in range(3)
    ]
    discovery = ExpertDiscovery(store, max_accounts=100, min_interactions=3)
    new = discovery.discover_from_tweets(tweets)
    assert "cryptocapo_" in new
    assert "tier10k" in new
