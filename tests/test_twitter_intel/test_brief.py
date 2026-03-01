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
    s.insert_signal("t1", "BTC", "crypto", "bullish")
    s.insert_signal("t2", "BTC", "crypto", "bullish")
    return s


def _mock_claude(text: str):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


def test_generate_returns_string_with_stats_footer(store_with_signals):
    mock_client = _mock_claude("📊 *Daily Trading Brief*\n\nBTC is hot")
    with patch("src.twitter_intel.brief.Anthropic", return_value=mock_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        gen = BriefGenerator(store_with_signals, min_expert_mentions=1)
        text = gen.generate()
    assert "📡" in text
    assert "Monitoring" in text


def test_generate_no_signals_returns_placeholder(tmp_path):
    store = TwitterIntelStore(db_path=str(tmp_path / "empty.db"))
    with patch("src.twitter_intel.brief.Anthropic"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        gen = BriefGenerator(store, min_expert_mentions=2)
        text = gen.generate()
    assert "No significant signals" in text


def test_generate_respects_min_expert_mentions(store_with_signals):
    """With min_expert_mentions=3 and only 2 experts, should return placeholder."""
    with patch("src.twitter_intel.brief.Anthropic"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        gen = BriefGenerator(store_with_signals, min_expert_mentions=3)
        text = gen.generate()
    assert "No significant signals" in text


def test_send_calls_telegram_api(store_with_signals):
    mock_client = _mock_claude("📊 Brief content")
    with patch("src.twitter_intel.brief.Anthropic", return_value=mock_client), \
         patch("src.twitter_intel.brief.requests.post") as mock_post, \
         patch.dict("os.environ", {
             "ANTHROPIC_API_KEY": "test",
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
    mock_client = _mock_claude("📊 Brief content")
    with patch("src.twitter_intel.brief.Anthropic", return_value=mock_client), \
         patch("src.twitter_intel.brief.requests.post", side_effect=Exception("down")), \
         patch.dict("os.environ", {
             "ANTHROPIC_API_KEY": "test",
             "TELEGRAM_BOT_TOKEN": "tok",
             "TELEGRAM_CHAT_ID": "123",
         }):
        gen = BriefGenerator(store_with_signals, min_expert_mentions=1)
        gen.send()
    log_files = list((tmp_path / "logs").glob("brief-*.txt"))
    assert len(log_files) == 1
