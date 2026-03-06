import logging
from datetime import datetime, timedelta, timezone

import yfinance as yf

logger = logging.getLogger(__name__)

_STOP_LOSS_PCT = 0.05   # 5% below entry = stop out
_EXPIRE_DAYS = 5        # close as 'expired' if neither target nor stop hit within 5 days

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


def open_trades_for_new_signals(store) -> int:
    """Open paper trades for any bullish stock signals not yet tracked. Returns count opened."""
    new_signals = store.get_new_signal_trades()
    opened = 0
    for sig in new_signals:
        ticker = sig["ticker"]
        price = _current_price(ticker)
        if price is None:
            logger.debug("No price for %s, skipping paper trade", ticker)
            continue

        target = sig.get("target_price") or (price * 1.10)
        stop = price * (1 - _STOP_LOSS_PCT)
        signal_time = sig.get("signal_time") or datetime.now(timezone.utc).isoformat()

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


def evaluate_open_trades(store) -> int:
    """Check prices for open trades; close WIN/LOSS/EXPIRED ones. Returns count closed."""
    trades = store.get_open_paper_trades()
    if not trades:
        return 0

    _price_cache.clear()
    now = datetime.now(timezone.utc)
    closed = 0

    for trade in trades:
        ticker = trade["ticker"]
        price = _current_price(ticker)
        if price is None:
            continue

        entry = trade["entry_price"]
        target = trade["target_price"]
        stop = trade["stop_price"]
        pnl_pct = (price - entry) / entry

        opened_at = datetime.fromisoformat(trade["opened_at"])
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)

        if price >= target:
            outcome = "win"
        elif price <= stop:
            outcome = "loss"
        elif (now - opened_at) >= timedelta(days=_EXPIRE_DAYS):
            outcome = "expired"
        else:
            continue

        store.close_paper_trade(trade["id"], price, outcome, pnl_pct)
        logger.info(
            "Closed [%s] %s: entry=$%.2f exit=$%.2f pnl=%.1f%%",
            outcome.upper(), ticker, entry, price, pnl_pct * 100,
        )
        closed += 1

    return closed
