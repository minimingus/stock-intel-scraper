import pytest
from unittest.mock import MagicMock, patch
from src.twitter_intel.brief import BriefGenerator
from src.twitter_intel.store import TwitterIntelStore


@pytest.fixture
def store_with_signals(tmp_path):
    s = TwitterIntelStore(db_path=str(tmp_path / "test.db"))
    s.upsert_expert("a")
    s.upsert_expert("b")
    s.insert_tweet("t1", "a", "", 0, 0)
    s.insert_tweet("t2", "b", "", 0, 0)
    s.insert_signal("t1", "AAPL", "stock", "bullish")
    s.insert_signal("t2", "AAPL", "stock", "bullish")
    return s


def test_generate_returns_string_with_stats_footer(store_with_signals):
    gen = BriefGenerator(store_with_signals, min_expert_mentions=1)
    text = gen.generate()
    assert "📡" in text
    assert "Monitoring" in text


def test_generate_no_signals_returns_placeholder(tmp_path):
    store = TwitterIntelStore(db_path=str(tmp_path / "empty.db"))
    gen = BriefGenerator(store, min_expert_mentions=2)
    text = gen.generate()
    assert "No qualified experts" in text or "No signals from proven experts" in text


def test_generate_respects_min_expert_mentions(store_with_signals):
    """With min_expert_mentions=3 and only 2 experts, signals section shows no qualified signals."""
    gen = BriefGenerator(store_with_signals, min_expert_mentions=3)
    text = gen.generate()
    # No signals meet the threshold so the signals section should show placeholder
    assert "No signals from proven experts" in text or "No qualified experts" in text


def test_two_section_structure(store_with_signals):
    """Brief must contain both expected section headers."""
    gen = BriefGenerator(store_with_signals, min_expert_mentions=1)
    text = gen.generate()
    assert "TOP EXPERTS" in text
    assert "SIGNALS TO WATCH" in text


def test_send_calls_telegram_api(store_with_signals):
    with patch("src.twitter_intel.brief.requests.post") as mock_post, \
         patch.dict("os.environ", {
             "TELEGRAM_BOT_TOKEN": "tok",
             "TELEGRAM_CHAT_ID": "123",
         }):
        mock_post.return_value.raise_for_status = MagicMock()
        gen = BriefGenerator(store_with_signals, min_expert_mentions=1)
        gen.send()
    mock_post.assert_called_once()
    assert "sendMessage" in mock_post.call_args[0][0]
    call_json = mock_post.call_args.kwargs["json"]
    assert call_json["parse_mode"] == "HTML"
    assert call_json["chat_id"] == "123"
    assert "text" in call_json


def test_send_saves_fallback_file_on_telegram_failure(store_with_signals, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("src.twitter_intel.brief.requests.post", side_effect=Exception("down")), \
         patch.dict("os.environ", {
             "TELEGRAM_BOT_TOKEN": "tok",
             "TELEGRAM_CHAT_ID": "123",
         }):
        gen = BriefGenerator(store_with_signals, min_expert_mentions=1)
        gen.send()
    log_files = list((tmp_path / "logs").glob("brief-*.txt"))
    assert len(log_files) == 1
