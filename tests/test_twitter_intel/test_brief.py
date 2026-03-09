from unittest.mock import MagicMock, patch
from src.twitter_intel.brief import BriefGenerator


def _make_store(mentions=None):
    store = MagicMock()
    store.get_hype_mentions.return_value = mentions or []
    store.get_expert_count.return_value = 12
    store.get_tweet_count_24h.return_value = 340
    return store


def _no_op_fetcher(ticker):
    prices = {"TSLA": {"price": 392.0, "mktcap": 1_200_000_000_000},
              "ONDS": {"price": 0.91,  "mktcap": 42_000_000}}
    return prices.get(ticker, {})


def test_generate_contains_most_hyped_header():
    store = _make_store([
        {"ticker": "TSLA", "handle": "alice", "tweet_time": "2026-03-09T10:00:00+00:00"},
        {"ticker": "TSLA", "handle": "bob",   "tweet_time": "2026-03-09T10:00:00+00:00"},
    ])
    bg = BriefGenerator(store, fetcher=_no_op_fetcher)
    brief = bg.generate()
    assert "MOST HYPED" in brief
    assert "$TSLA" in brief
    assert "×2" in brief


def test_generate_penny_section_present():
    store = _make_store([
        {"ticker": "ONDS", "handle": "alice", "tweet_time": "2026-03-09T10:00:00+00:00"},
    ])
    bg = BriefGenerator(store, fetcher=_no_op_fetcher)
    brief = bg.generate()
    assert "PENNY" in brief
    assert "$ONDS" in brief


def test_generate_no_signals_shows_placeholder():
    store = _make_store([])
    bg = BriefGenerator(store, fetcher=_no_op_fetcher)
    brief = bg.generate()
    assert "No signals" in brief


def test_generate_shows_handles():
    store = _make_store([
        {"ticker": "NVDA", "handle": "alice", "tweet_time": "2026-03-09T10:00:00+00:00"},
        {"ticker": "NVDA", "handle": "bob",   "tweet_time": "2026-03-09T10:00:00+00:00"},
    ])
    bg = BriefGenerator(store, fetcher=_no_op_fetcher)
    brief = bg.generate()
    assert "@alice" in brief
    assert "@bob"   in brief


def test_generate_footer_shows_monitoring_stats():
    store = _make_store([])
    bg = BriefGenerator(store, fetcher=_no_op_fetcher)
    brief = bg.generate()
    assert "12" in brief   # expert_count
    assert "340" in brief  # tweet_count


def test_send_calls_telegram_api():
    store = _make_store([])
    bg = BriefGenerator(store, fetcher=_no_op_fetcher)
    with patch("src.twitter_intel.brief.requests.post") as mock_post:
        mock_post.return_value.raise_for_status = MagicMock()
        import os
        os.environ["TELEGRAM_BOT_TOKEN"] = "tok"
        os.environ["TELEGRAM_CHAT_ID"]   = "123"
        bg.send()
        mock_post.assert_called_once()
