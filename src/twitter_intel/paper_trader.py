import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import yfinance as yf

logger = logging.getLogger(__name__)

_STOP_LOSS_PCT = 0.05   # 5% below entry = stop out
_EXPIRE_DAYS = 5        # close as 'expired' if neither target nor stop hit within 5 days


def _to_yf_crypto_ticker(ticker: str) -> str:
    """Convert bare crypto ticker to yfinance symbol, e.g. BTC -> BTC-USD."""
    if ticker.endswith("-USD"):
        return ticker
    return f"{ticker}-USD"


_price_cache: dict = {}


def _current_price(ticker: str) -> float | None:
    if ticker in _price_cache:
        return _price_cache[ticker]
    try:
        hist = yf.Ticker(ticker).history(period="1d", interval="5m")
        if not hist.empty:
            price = float(hist["Close"].iloc[-1])
            _price_cache[ticker] = price
            return price
    except Exception as e:
        logger.debug("Price fetch failed for %s: %s", ticker, e)
    return None


def _price_history_since(ticker: str, since: datetime):
    """
    Fetch hourly OHLC history from `since` to now.
    Returns a DataFrame with UTC-indexed rows, or None on failure.
    """
    try:
        start_str = since.date().isoformat()
        hist = yf.Ticker(ticker).history(start=start_str, interval="1h", auto_adjust=True)
        if hist.empty:
            return None
        hist.index = hist.index.tz_convert("UTC")
        return hist[hist.index >= since]
    except Exception as e:
        logger.debug("History fetch failed for %s: %s", ticker, e)
        return None


def _atr_stop(ticker: str, entry: float) -> float:
    """Compute stop price using 1.5× ATR(14). Clamped to 2%-10% below entry."""
    try:
        hist = yf.Ticker(ticker).history(period="20d", interval="1d", auto_adjust=True)
        if len(hist) < 15:
            return entry * (1 - _STOP_LOSS_PCT)
        high = hist["High"].iloc[-14:].values
        low = hist["Low"].iloc[-14:].values
        prev_close = hist["Close"].iloc[-15:-1].values
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
        atr = tr.mean()
        stop = entry - 1.5 * atr
        # Clamp: never closer than 2% or wider than 10%
        stop = max(entry * 0.90, min(entry * 0.98, stop))
        return stop
    except Exception as e:
        logger.debug("ATR fetch failed for %s: %s", ticker, e)
        return entry * (1 - _STOP_LOSS_PCT)


def open_trades_for_new_signals(store) -> int:
    """Open paper trades for any bullish stock signals not yet tracked. Returns count opened."""
    new_signals = store.get_new_signal_trades()
    opened = 0
    for sig in new_signals:
        ticker = sig["ticker"]
        signal_time = sig.get("signal_time") or datetime.now(timezone.utc).isoformat()

        # Skip stale signals
        try:
            st = datetime.fromisoformat(signal_time)
            if st.tzinfo is None:
                st = st.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - st).total_seconds() / 3600
            if age_hours > 1.0:
                logger.debug("Skipping stale signal %s (%.1fh old)", ticker, age_hours)
                continue
        except Exception:
            pass

        if not sig.get("target_price"):
            logger.debug("Skipping %s — no explicit price target in tweet", ticker)
            continue

        price = _current_price(ticker)
        if price is None:
            logger.debug("No price for %s, skipping paper trade", ticker)
            continue

        target = sig["target_price"]
        stop = _atr_stop(ticker, price)

        store.open_paper_trade(
            ticker=ticker,
            expert_handle=sig["handle"],
            tweet_id=sig["tweet_id"],
            entry_price=price,
            target_price=target,
            stop_price=stop,
            signal_time=signal_time,
        )
        logger.info(
            "Opened paper trade: %s @ $%.2f → $%.2f (stop $%.2f) for @%s",
            ticker, price, target, stop, sig["handle"],
        )
        opened += 1
    return opened


def open_crypto_trades_for_new_signals(store) -> int:
    """Open paper trades for bullish crypto signals not yet tracked. Returns count opened."""
    new_signals = store.get_new_crypto_signal_trades()
    opened = 0
    for sig in new_signals:
        ticker = _to_yf_crypto_ticker(sig["ticker"])  # e.g. BTC-USD
        signal_time = sig.get("signal_time") or datetime.now(timezone.utc).isoformat()

        try:
            st = datetime.fromisoformat(signal_time)
            if st.tzinfo is None:
                st = st.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - st).total_seconds() / 3600
            if age_hours > 1.0:
                logger.debug("Skipping stale crypto signal %s (%.1fh old)", ticker, age_hours)
                continue
        except Exception:
            pass

        if not sig.get("target_price"):
            logger.debug("Skipping %s — no explicit price target in tweet", ticker)
            continue

        price = _current_price(ticker)
        if price is None:
            logger.debug("No price for %s, skipping crypto paper trade", ticker)
            continue

        target = sig["target_price"]
        stop = _atr_stop(ticker, price)

        store.open_paper_trade(
            ticker=ticker,
            expert_handle=sig["handle"],
            tweet_id=sig["tweet_id"],
            entry_price=price,
            target_price=target,
            stop_price=stop,
            signal_time=signal_time,
        )
        logger.info(
            "Opened crypto paper trade: %s @ $%.2f → $%.2f (stop $%.2f) for @%s",
            ticker, price, target, stop, sig["handle"],
        )
        opened += 1
    return opened


def evaluate_open_trades(store) -> int:
    """
    Evaluate all open paper trades using full OHLC history since each trade opened.
    This catches targets/stops that were hit between runs, not just at run time.
    Returns count of trades closed.
    """
    trades = store.get_open_paper_trades()
    if not trades:
        return 0

    _price_cache.clear()
    now = datetime.now(timezone.utc)
    closed = 0

    for trade in trades:
        ticker = trade["ticker"]
        entry = trade["entry_price"]
        target = trade["target_price"]
        stop = trade["stop_price"]

        opened_at = datetime.fromisoformat(trade["opened_at"])
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)

        hist = _price_history_since(ticker, opened_at)

        if hist is None or hist.empty:
            # Fall back to current price only
            price = _current_price(ticker)
            if price is None:
                continue
            pnl_pct = (price - entry) / entry
            if (now - opened_at) >= timedelta(days=_EXPIRE_DAYS):
                store.close_paper_trade(trade["id"], price, "expired", pnl_pct)
                closed += 1
            continue

        # Track best and worst prices seen over the trade's lifetime
        max_high = float(hist["High"].max())
        min_low = float(hist["Low"].min())
        max_gain_pct = (max_high - entry) / entry
        max_drawdown_pct = (min_low - entry) / entry  # negative = drawdown

        # Find the first candle where target was hit (High >= target)
        target_hits = hist[hist["High"] >= target]
        # Find the first candle where stop was hit (Low <= stop)
        stop_hits = hist[hist["Low"] <= stop]

        target_time = target_hits.index[0] if len(target_hits) else None
        stop_time = stop_hits.index[0] if len(stop_hits) else None

        outcome = None
        exit_price = None
        exit_time = None

        if target_time and (stop_time is None or target_time <= stop_time):
            outcome = "win"
            exit_price = target
            exit_time = target_time
        elif stop_time:
            outcome = "loss"
            exit_price = stop
            exit_time = stop_time
        elif (now - opened_at) >= timedelta(days=_EXPIRE_DAYS):
            outcome = "expired"
            exit_price = float(hist["Close"].iloc[-1])
            exit_time = now

        if outcome is None:
            continue  # still open, no action

        pnl_pct = (exit_price - entry) / entry
        days_held = (exit_time - opened_at).total_seconds() / 86400 if exit_time else None

        store.close_paper_trade(
            trade_id=trade["id"],
            exit_price=exit_price,
            outcome=outcome,
            pnl_pct=pnl_pct,
            max_gain_pct=max_gain_pct,
            max_drawdown_pct=max_drawdown_pct,
            days_held=days_held,
        )
        logger.info(
            "Closed [%s] %s: entry=$%.2f exit=$%.2f pnl=%.1f%% "
            "max_gain=%.1f%% max_dd=%.1f%% held=%.1fd",
            outcome.upper(), ticker, entry, exit_price,
            pnl_pct * 100, max_gain_pct * 100, max_drawdown_pct * 100,
            days_held or 0,
        )
        closed += 1

    return closed
