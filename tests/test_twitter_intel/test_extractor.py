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


def test_run_processes_all_new_tweets(store):
    mock_client = _mock_claude([
        {"tweet_id": "t1", "ticker": "BTC", "asset_type": "crypto", "sentiment": "bullish"}
    ])
    with patch("src.twitter_intel.extractor.Anthropic", return_value=mock_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        extractor = SignalExtractor(store)
        count = extractor.run()
    assert count == 1
