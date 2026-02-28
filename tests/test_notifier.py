from unittest.mock import patch, MagicMock


def _make_notifier():
    from src.notifier import TelegramNotifier
    return TelegramNotifier(bot_token="test_token", chat_id="123456")


def test_send_posts_to_telegram_api():
    with patch("src.notifier.requests.post") as mock_post:
        mock_post.return_value.ok = True
        notifier = _make_notifier()
        notifier.send("Hello from trader")

    mock_post.assert_called_once()
    payload = mock_post.call_args.kwargs["json"]
    assert payload["chat_id"] == "123456"
    assert "Hello from trader" in payload["text"]


def test_send_trade_alert_includes_dry_run_prefix():
    with patch("src.notifier.requests.post") as mock_post:
        mock_post.return_value.ok = True
        notifier = _make_notifier()
        notifier.send_trade_alert(
            question="Will Fed cut rates?",
            action="BUY_YES",
            amount_usdc=4.0,
            confidence=0.80,
            reasoning="Fed signaled cuts",
            dry_run=True,
        )

    text = mock_post.call_args.kwargs["json"]["text"]
    assert "[DRY RUN]" in text
    assert "BUY YES" in text
    assert "$4.00" in text
    assert "80%" in text


def test_send_trade_alert_no_prefix_when_live():
    with patch("src.notifier.requests.post") as mock_post:
        mock_post.return_value.ok = True
        notifier = _make_notifier()
        notifier.send_trade_alert(
            question="Q", action="BUY_NO", amount_usdc=3.0,
            confidence=0.75, reasoning="reason", dry_run=False,
        )

    text = mock_post.call_args.kwargs["json"]["text"]
    assert "[DRY RUN]" not in text
    assert "BUY NO" in text


def test_send_cycle_summary_includes_counts():
    with patch("src.notifier.requests.post") as mock_post:
        mock_post.return_value.ok = True
        notifier = _make_notifier()
        notifier.send_cycle_summary(
            markets_analyzed=20, bets_placed=2, total_usdc=8.0, dry_run=True
        )

    text = mock_post.call_args.kwargs["json"]["text"]
    assert "20" in text
    assert "2" in text
    assert "$8.00" in text
    assert "[DRY RUN]" in text
