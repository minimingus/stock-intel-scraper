import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import yfinance as yf

logger = logging.getLogger(__name__)

_STOP_LOSS_PCT = 0.05   # 5% below entry = stop out
_DAY_TRADE_CLOSE_UTC = 21  # 4 PM ET in UTC


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


# US market hours in UTC: 14:30–21:00
_MARKET_OPEN_UTC = 14 * 60 + 30   # minutes since midnight
_MARKET_CLOSE_UTC = 21 * 60        # minutes since midnight


def _is_market_hours(dt: datetime) -> bool:
    """Return True if dt falls within regular US equity market hours (UTC)."""
    mins = dt.hour * 60 + dt.minute
    return _MARKET_OPEN_UTC <= mins < _MARKET_CLOSE_UTC


def _price_at(ticker: str, at: datetime) -> float | None:
    """Fetch price at or just after `at`. Uses 5-min bars during market hours, 1h otherwise."""
    interval = "5m" if _is_market_hours(at) else "1h"
    try:
        start = at.date().isoformat()
        end_dt = at + timedelta(days=2)
        end = end_dt.date().isoformat()
        hist = yf.Ticker(ticker).history(start=start, end=end, interval=interval, auto_adjust=True)
        if hist.empty:
            return None
        hist.index = hist.index.tz_convert("UTC")
        after = hist[hist.index >= at]
        if not after.empty:
            return float(after["Close"].iloc[0])
        return float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.debug("Historical price fetch failed for %s at %s: %s", ticker, at, e)
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


_SPY_CRASH_THRESHOLD = -0.03   # -3% vs prior close triggers crash mode
_spy_regime_cache: dict = {}


def _spy_regime() -> str:
    """
    Returns 'bull', 'bear', or 'crash' based on SPY vs its 20-day SMA.
    - 'crash': today's close is down >3% vs prior close
    - 'bull':  SPY close > 20D SMA
    - 'bear':  SPY close <= 20D SMA
    Cached per session; cleared by evaluate_open_trades() each cycle.
    """
    if "regime" in _spy_regime_cache:
        return _spy_regime_cache["regime"]
    current = sma20 = 0.0
    try:
        hist = yf.Ticker("SPY").history(period="25d", interval="1d", auto_adjust=True)
        if len(hist) < 20:
            _spy_regime_cache["regime"] = "bull"
            return "bull"
        hist.index = hist.index.tz_convert("UTC")
        closes = hist["Close"].values
        current = float(closes[-1])
        today_open = float(hist["Open"].iloc[-1])
        sma20 = float(closes[-20:].mean())
        intraday_chg = (current - today_open) / today_open
        if intraday_chg <= _SPY_CRASH_THRESHOLD:
            regime = "crash"
        elif current > sma20:
            regime = "bull"
        else:
            regime = "bear"
    except Exception as e:
        logger.warning("SPY regime check failed: %s — defaulting to bull", e)
        regime = "bull"
    _spy_regime_cache["regime"] = regime
    logger.info("Market regime: %s (SPY $%.2f vs SMA20 $%.2f)", regime, current, sma20)
    return regime


def _expiry_for_trade(trade_type: str, signal_dt: datetime) -> datetime:
    """Return the expiry datetime for a trade based on its type.

    Day trades expire at market close (21:00 UTC) on the signal day,
    or the next day if the signal was posted after market close.
    Swing trades expire 14 days from the signal.
    """
    if trade_type == "day":
        expiry = signal_dt.replace(hour=_DAY_TRADE_CLOSE_UTC, minute=0, second=0, microsecond=0)
        if expiry <= signal_dt:
            expiry += timedelta(days=1)
        return expiry
    return signal_dt + timedelta(days=14)


def open_trades_for_new_signals(store) -> int:
    """Open paper trades for any bullish stock signals not yet tracked. Returns count opened."""
    new_signals = store.get_new_signal_trades()
    regime = _spy_regime()
    if regime == "crash":
        logger.warning("Market crash detected — suspending all new paper trade opens")
        return 0
    opened = 0
    for sig in new_signals:
        ticker = sig["ticker"]
        signal_time = sig.get("signal_time") or datetime.now(timezone.utc).isoformat()

        # Determine if signal is recent (< 1h) or historical
        signal_dt = None
        try:
            signal_dt = datetime.fromisoformat(signal_time)
            if signal_dt.tzinfo is None:
                signal_dt = signal_dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass

        age_hours = (datetime.now(timezone.utc) - signal_dt).total_seconds() / 3600 if signal_dt else 0

        if age_hours <= 1.0:
            price = _current_price(ticker)
        else:
            # Historical signal: fetch price at the time of the tweet
            price = _price_at(ticker, signal_dt) if signal_dt else None
        if price is None:
            logger.debug("No price for %s, skipping paper trade", ticker)
            continue

        # Entry zone validation: skip if price is >15% above suggested entry
        entry_suggested = sig.get("entry_price_suggested")
        if entry_suggested and price > entry_suggested * 1.15:
            logger.info(
                "Skipped %s for @%s: price $%.2f is >15%% above suggested entry $%.2f",
                ticker, sig["handle"], price, entry_suggested,
            )
            continue

        if regime == "bear" and sig.get("specificity", 0) < 2:
            logger.debug(
                "Bear market: skipping low-specificity signal %s for @%s (specificity=%d)",
                ticker, sig["handle"], sig.get("specificity", 0),
            )
            continue

        # Use explicit target if available, otherwise default to +10% from entry
        explicit_target = sig.get("target_price")
        target = explicit_target if explicit_target and explicit_target > price else price * 1.10

        # Use expert-specified stop if plausible (5-20% below entry), else ATR
        stop_suggested = sig.get("stop_price_suggested")
        if stop_suggested and price * 0.80 <= stop_suggested <= price * 0.95:
            stop = stop_suggested
            stop_source = "expert"
        else:
            stop = _atr_stop(ticker, price)
            stop_source = "ATR"

        rr = (target - price) / (price - stop) if price > stop else None

        trade_type = sig.get("trade_type", "swing")
        store.open_paper_trade(
            ticker=ticker,
            expert_handle=sig["handle"],
            tweet_id=sig["tweet_id"],
            entry_price=price,
            target_price=target,
            stop_price=stop,
            signal_time=signal_time,
            trade_type=trade_type,
        )
        rr_str = f" R:R 1:{rr:.1f}" if rr else ""
        logger.info(
            "Opened paper trade: %s @ $%.2f → $%.2f%s (stop $%.2f [%s])%s for @%s",
            ticker, price, target,
            "" if explicit_target else " [default +10%]",
            stop, stop_source, rr_str, sig["handle"],
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

        signal_dt = None
        try:
            signal_dt = datetime.fromisoformat(signal_time)
            if signal_dt.tzinfo is None:
                signal_dt = signal_dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass

        age_hours = (datetime.now(timezone.utc) - signal_dt).total_seconds() / 3600 if signal_dt else 0

        if age_hours <= 1.0:
            price = _current_price(ticker)
        else:
            price = _price_at(ticker, signal_dt) if signal_dt else None
        if price is None:
            logger.debug("No price for %s, skipping crypto paper trade", ticker)
            continue

        explicit_target = sig.get("target_price")
        target = explicit_target if explicit_target and explicit_target > price else price * 1.10
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
            "Opened crypto paper trade: %s @ $%.2f → $%.2f%s (stop $%.2f) for @%s",
            ticker, price, target,
            "" if explicit_target else " [default +10%]",
            stop, sig["handle"],
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

    _spy_regime_cache.clear()
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

        # Use signal_time as trade start for historical accuracy; fall back to opened_at
        trade_start = opened_at
        raw_signal_time = trade.get("signal_time")
        if raw_signal_time:
            try:
                st = datetime.fromisoformat(raw_signal_time)
                if st.tzinfo is None:
                    st = st.replace(tzinfo=timezone.utc)
                trade_start = st
            except Exception:
                pass

        hist = _price_history_since(ticker, trade_start)

        if hist is None or hist.empty:
            # Fall back to current price only
            price = _current_price(ticker)
            if price is None:
                continue
            pnl_pct = (price - entry) / entry
            if now >= _expiry_for_trade(trade.get("trade_type", "swing"), trade_start):
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
        elif now >= _expiry_for_trade(trade.get("trade_type", "swing"), trade_start):
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
