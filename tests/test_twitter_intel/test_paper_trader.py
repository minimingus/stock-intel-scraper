import pytest
from datetime import datetime, timezone
from unittest.mock import patch
import pandas as pd


def _make_hist(prices: list, index_times: list) -> pd.DataFrame:
    idx = pd.DatetimeIndex(index_times, tz="UTC")
    return pd.DataFrame(
        {"Close": prices, "High": prices, "Low": prices, "Open": prices},
        index=idx,
    )


def test_price_at_uses_5min_during_market_hours():
    """Signals during market hours (14:30-21:00 UTC) should use 5-min bars."""
    from src.twitter_intel.paper_trader import _price_at

    signal_dt = datetime(2025, 1, 15, 15, 0, tzinfo=timezone.utc)
    fake_hist = _make_hist(
        [142.50],
        [datetime(2025, 1, 15, 15, 5, tzinfo=timezone.utc)],
    )

    with patch("src.twitter_intel.paper_trader.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = fake_hist
        price = _price_at("AAPL", signal_dt)
        call_kwargs = mock_ticker.return_value.history.call_args[1]
        assert call_kwargs.get("interval") == "5m"
        assert price == pytest.approx(142.50)


def test_price_at_uses_1h_outside_market_hours():
    """Signals outside market hours should use hourly bars."""
    from src.twitter_intel.paper_trader import _price_at

    signal_dt = datetime(2025, 1, 15, 2, 0, tzinfo=timezone.utc)
    fake_hist = _make_hist(
        [140.00],
        [datetime(2025, 1, 15, 14, 0, tzinfo=timezone.utc)],
    )

    with patch("src.twitter_intel.paper_trader.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = fake_hist
        _price_at("AAPL", signal_dt)
        call_kwargs = mock_ticker.return_value.history.call_args[1]
        assert call_kwargs.get("interval") == "1h"


def test_day_trade_expires_end_of_signal_day():
    """Day trades must expire at 21:00 UTC (4 PM ET) on the signal day."""
    from src.twitter_intel.paper_trader import _expiry_for_trade
    from datetime import datetime, timezone

    signal_dt = datetime(2025, 1, 15, 15, 0, tzinfo=timezone.utc)
    expiry = _expiry_for_trade("day", signal_dt)
    assert expiry == datetime(2025, 1, 15, 21, 0, tzinfo=timezone.utc)


def test_swing_trade_expires_14_days():
    """Swing trades must expire 14 days after the signal."""
    from src.twitter_intel.paper_trader import _expiry_for_trade
    from datetime import datetime, timezone, timedelta

    signal_dt = datetime(2025, 1, 15, 15, 0, tzinfo=timezone.utc)
    expiry = _expiry_for_trade("swing", signal_dt)
    assert expiry == signal_dt + timedelta(days=14)
