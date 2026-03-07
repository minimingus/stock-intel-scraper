import json
import pytest
from unittest.mock import MagicMock, patch
from src.twitter_intel.extractor import SignalExtractor
from src.twitter_intel.store import TwitterIntelStore


@pytest.fixture
def store(tmp_path):
    s = TwitterIntelStore(db_path=str(tmp_path / "test.db"))
    s.upsert_expert("trader1")
    s.insert_tweet("t1", "trader1", "$BTC breaking $90k, very bullish", 10, 5)
    return s


def _mock_claude(response_json: list):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=json.dumps(response_json))]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


def test_extract_batch_inserts_signals(store):
    mock_client = _mock_claude([
        {"tweet_id": "t1", "ticker": "BTC", "asset_type": "crypto", "sentiment": "bullish"}
    ])
    with patch("src.twitter_intel.extractor.Anthropic", return_value=mock_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        extractor = SignalExtractor(store)
        count = extractor.extract_batch([{"tweet_id": "t1", "text": "$BTC bullish"}])
    assert count == 1
    signals = store.get_signals_for_brief(24)
    assert signals[0]["ticker"] == "BTC"


def test_extract_batch_uppercases_ticker(store):
    mock_client = _mock_claude([
        {"tweet_id": "t1", "ticker": "btc", "asset_type": "crypto", "sentiment": "bullish"}
    ])
    with patch("src.twitter_intel.extractor.Anthropic", return_value=mock_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        extractor = SignalExtractor(store)
        extractor.extract_batch([{"tweet_id": "t1", "text": "btc"}])
    signals = store.get_signals_for_brief(24)
    assert signals[0]["ticker"] == "BTC"


def test_extract_batch_returns_zero_on_api_failure(store):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API error")
    with patch("src.twitter_intel.extractor.Anthropic", return_value=mock_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        extractor = SignalExtractor(store)
        count = extractor.extract_batch([{"tweet_id": "t1", "text": "test"}])
    assert count == 0


def test_extract_batch_skips_malformed_signal(store):
    mock_client = _mock_claude([
        {"tweet_id": "t1", "ticker": "BTC", "asset_type": "crypto", "sentiment": "bullish"},
        {"tweet_id": "t1"},  # missing required fields
    ])
    with patch("src.twitter_intel.extractor.Anthropic", return_value=mock_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        extractor = SignalExtractor(store)
        count = extractor.extract_batch([{"tweet_id": "t1", "text": "test"}])
    assert count == 1


def test_extract_batch_empty_input_returns_zero(store):
    with patch("src.twitter_intel.extractor.Anthropic"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        extractor = SignalExtractor(store)
        count = extractor.extract_batch([])
    assert count == 0


def test_extract_batch_handles_markdown_fenced_response(store):
    """Claude sometimes wraps JSON in markdown fences — must be handled."""
    fenced = "```json\n" + json.dumps([
        {"tweet_id": "t1", "ticker": "BTC", "asset_type": "crypto", "sentiment": "bullish"}
    ]) + "\n```"
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=fenced)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    with patch("src.twitter_intel.extractor.Anthropic", return_value=mock_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        extractor = SignalExtractor(store)
        count = extractor.extract_batch([{"tweet_id": "t1", "text": "$BTC bullish"}])
    assert count == 1


def test_run_processes_all_new_tweets(store):
    mock_client = _mock_claude([
        {"tweet_id": "t1", "ticker": "BTC", "asset_type": "crypto", "sentiment": "bullish"}
    ])
    with patch("src.twitter_intel.extractor.Anthropic", return_value=mock_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        extractor = SignalExtractor(store)
        count = extractor.run()
    assert count == 1


def test_retweet_is_skipped():
    """Retweet tweets must never produce signals."""
    from unittest.mock import MagicMock
    from src.twitter_intel.extractor import SignalExtractor

    store = MagicMock()
    extractor = SignalExtractor(store)
    tweets = [
        {"tweet_id": "1", "text": "RT @sometrader: $AAPL breaking out buy here bullish setup"},
        {"tweet_id": "2", "text": "via @guru: $TSLA long momentum play pump"},
    ]
    result = extractor.extract_batch(tweets)
    assert result == 0
    store.insert_signal.assert_not_called()


def test_original_tweet_is_not_skipped():
    """Non-retweet bullish tweets with TA must produce signals."""
    from unittest.mock import MagicMock
    from src.twitter_intel.extractor import SignalExtractor

    store = MagicMock()
    extractor = SignalExtractor(store)
    tweets = [
        {"tweet_id": "3", "text": "$AAPL breaking out, bullish setup, buy here"},
    ]
    extractor.extract_batch(tweets)
    assert store.insert_signal.called


def test_specificity_zero_for_vague_tweet():
    from src.twitter_intel.extractor import _tweet_specificity
    text = "$AAPL looking bullish, buy the breakout"
    assert _tweet_specificity(text) == 0


def test_specificity_three_for_full_setup():
    from src.twitter_intel.extractor import _tweet_specificity
    text = "Entry $145, stop $138, target $160 on $AAPL"
    assert _tweet_specificity(text) == 3


def test_specificity_one_for_stop_only():
    from src.twitter_intel.extractor import _tweet_specificity
    text = "$AAPL bullish. Stop $138 if it breaks down."
    assert _tweet_specificity(text) == 1
