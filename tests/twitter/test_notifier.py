import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from src.twitter.notifier import TelegramNotifier


def _notifier():
    return TelegramNotifier(bot_token="test_token", chat_id="12345")


def test_send_digest_posts_to_telegram():
    notifier = _notifier()
    signals = [
        {"topic": "new_release", "summary": "Anthropic launched Claude 4.",
         "tweets": [{"author": "AnthropicAI", "text": "", "url": ""}]},
    ]
    start = datetime(2026, 2, 28, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 28, 14, 0, tzinfo=timezone.utc)

    with patch("src.twitter.notifier.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier.send_digest(signals, start, end)
        mock_post.assert_called_once()
        body = mock_post.call_args[1]["json"]
        assert "AI Pulse" in body["text"]
        assert "New Releases" in body["text"]
        assert "Claude 4" in body["text"]
        assert "@AnthropicAI" in body["text"]


def test_send_digest_skips_when_no_signals():
    notifier = _notifier()
    with patch("src.twitter.notifier.requests.post") as mock_post:
        notifier.send_digest([], datetime.now(), datetime.now())
        mock_post.assert_not_called()


def test_send_daily_brief_includes_header_and_narrative():
    notifier = _notifier()
    with patch("src.twitter.notifier.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier.send_daily_brief("Today was huge for AI.", datetime(2026, 2, 28))
        body = mock_post.call_args[1]["json"]
        assert "Daily AI Brief" in body["text"]
        assert "Today was huge for AI." in body["text"]
        assert "February 28, 2026" in body["text"]
