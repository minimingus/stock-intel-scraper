import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
from src.twitter.fetcher import TweetFetcher
from src.twitter.signal_store import SignalStore


def _raw_tweet(id, text, likes=10, is_retweet=False, age_minutes=30):
    t = MagicMock()
    t.id = id
    t.full_text = text
    t.favorite_count = likes
    t.retweeted_tweet = MagicMock() if is_retweet else None
    t.created_at_datetime = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    return t


def test_fetch_returns_new_tweets_and_deduplicates(tmp_path):
    with patch("src.twitter.fetcher.Client") as MockClient:
        inst = MockClient.return_value
        inst.load_cookies = MagicMock()
        mock_user = AsyncMock()
        mock_user.get_tweets = AsyncMock(return_value=[
            _raw_tweet("t1", "Claude 4 release is here!"),
            _raw_tweet("t2", "New Cursor update dropped"),
        ])
        inst.get_user_by_screen_name = AsyncMock(return_value=mock_user)

        cookies = tmp_path / "cookies.json"
        cookies.write_text("[]")
        store = SignalStore(tmp_path / "signals.json", tmp_path / "seen.json")

        fetcher = TweetFetcher("user", "pass", "e@x.com", cookies_path=cookies)
        tweets = fetcher.fetch(["AnthropicAI"], since_hours=4, store=store)
        assert len(tweets) == 2

        # Second call: all seen, returns empty
        tweets2 = fetcher.fetch(["AnthropicAI"], since_hours=4, store=store)
        assert len(tweets2) == 0


def test_fetch_skips_tweets_older_than_window(tmp_path):
    with patch("src.twitter.fetcher.Client") as MockClient:
        inst = MockClient.return_value
        inst.load_cookies = MagicMock()
        old_tweet = _raw_tweet("t_old", "An old GPT tweet", age_minutes=300)
        mock_user = AsyncMock()
        mock_user.get_tweets = AsyncMock(return_value=[old_tweet])
        inst.get_user_by_screen_name = AsyncMock(return_value=mock_user)

        cookies = tmp_path / "cookies.json"
        cookies.write_text("[]")

        fetcher = TweetFetcher("user", "pass", "e@x.com", cookies_path=cookies)
        tweets = fetcher.fetch(["OpenAI"], since_hours=4)
        assert tweets == []


def test_fetch_handles_account_error_gracefully(tmp_path):
    with patch("src.twitter.fetcher.Client") as MockClient:
        inst = MockClient.return_value
        inst.load_cookies = MagicMock()
        inst.get_user_by_screen_name = AsyncMock(side_effect=Exception("User not found"))

        cookies = tmp_path / "cookies.json"
        cookies.write_text("[]")

        fetcher = TweetFetcher("user", "pass", "e@x.com", cookies_path=cookies)
        tweets = fetcher.fetch(["ghost_account"], since_hours=4)
        assert tweets == []
