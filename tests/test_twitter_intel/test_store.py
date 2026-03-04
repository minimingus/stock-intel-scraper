import pytest
from src.twitter_intel.store import TwitterIntelStore


@pytest.fixture
def store(tmp_path):
    return TwitterIntelStore(db_path=str(tmp_path / "test.db"))


def test_upsert_expert_and_retrieve(store):
    store.upsert_expert("trader1", source="seed")
    store.upsert_expert("trader2", source="discovered")
    experts = store.get_active_experts()
    assert "trader1" in experts
    assert "trader2" in experts


def test_upsert_expert_is_idempotent(store):
    store.upsert_expert("trader1")
    store.upsert_expert("trader1")
    assert store.get_active_experts().count("trader1") == 1


def test_insert_tweet_appears_in_new_tweets(store):
    store.upsert_expert("trader1")
    store.insert_tweet("t1", "trader1", "BTC going to 100k", 10, 5)
    new = store.get_new_tweets()
    assert len(new) == 1
    assert new[0]["tweet_id"] == "t1"


def test_tweet_disappears_from_new_after_signal_inserted(store):
    store.upsert_expert("trader1")
    store.insert_tweet("t1", "trader1", "BTC going to 100k", 10, 5)
    store.insert_signal("t1", "BTC", "crypto", "bullish")
    new = store.get_new_tweets()
    assert len(new) == 0


def test_get_signals_for_brief_ranks_by_expert_count(store):
    store.upsert_expert("a")
    store.upsert_expert("b")
    store.insert_tweet("t1", "a", "BTC", 0, 0)
    store.insert_tweet("t2", "b", "BTC", 0, 0)
    store.insert_tweet("t3", "a", "ETH", 0, 0)
    store.insert_signal("t1", "BTC", "crypto", "bullish")
    store.insert_signal("t2", "BTC", "crypto", "bullish")
    store.insert_signal("t3", "ETH", "crypto", "neutral")
    signals = store.get_signals_for_brief(24)
    assert signals[0]["ticker"] == "BTC"
    assert signals[0]["expert_count"] == 2
    assert signals[1]["ticker"] == "ETH"


def test_prune_old_tweets_removes_stale_rows(store):
    store.upsert_expert("a")
    store.insert_tweet("t1", "a", "old tweet", 0, 0)
    store.conn.execute(
        "UPDATE tweets SET scraped_at = '2020-01-01T00:00:00+00:00' WHERE tweet_id = 't1'"
    )
    store.conn.commit()
    store.prune_old_tweets(days=7)
    assert len(store.get_new_tweets()) == 0


def test_get_expert_count(store):
    store.upsert_expert("a")
    store.upsert_expert("b")
    assert store.get_expert_count() == 2


def test_get_tweet_count_24h(store):
    store.upsert_expert("a")
    store.insert_tweet("t1", "a", "recent", 0, 0)
    assert store.get_tweet_count_24h() == 1
