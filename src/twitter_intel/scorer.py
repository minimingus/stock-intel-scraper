import logging
from datetime import datetime, timedelta, timezone

import yfinance as yf

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)

_price_cache: dict = {}


def _fetch_change_pct(ticker: str, asset_type: str, hours: int = 24) -> float | None:
    """Return % price change over last `hours`. Positive = up. None if unavailable."""
    cache_key = (ticker, asset_type, hours)
    if cache_key in _price_cache:
        return _price_cache[cache_key]

    symbol = f"{ticker}-USD" if asset_type == "crypto" else ticker
    try:
        days = max(2, hours // 24 + 2)
        hist = yf.Ticker(symbol).history(period=f"{days}d", interval="1h", auto_adjust=True)
        if len(hist) < 2:
            _price_cache[cache_key] = None
            return None

        price_now = float(hist["Close"].iloc[-1])
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        past = hist[hist.index.tz_convert("UTC") <= cutoff]
        if past.empty:
            past = hist.iloc[:1]
        price_then = float(past["Close"].iloc[-1])
        result = (price_now - price_then) / price_then * 100 if price_then else None
    except Exception as e:
        logger.debug("Price fetch failed for %s: %s", symbol, e)
        result = None

    _price_cache[cache_key] = result
    return result


class ExpertScorer:
    def __init__(self, store: TwitterIntelStore, lookback_hours: int = 168):
        self.store = store
        self.lookback_hours = lookback_hours  # default 7 days

    def score(self) -> list[dict]:
        """
        Score experts by prediction accuracy.
        Returns list of {handle, hit_rate, hits, total} sorted by hit_rate desc.
        Only includes experts with >= 2 scored signals.
        """
        signals = self.store.get_signals_with_handles(self.lookback_hours)
        if not signals:
            return []

        scores: dict[str, dict] = {}
        seen_ticker_prices: dict = {}

        for sig in signals:
            ticker = sig["ticker"]
            asset_type = sig["asset_type"]
            handle = sig["handle"]

            if ticker not in seen_ticker_prices:
                seen_ticker_prices[ticker] = _fetch_change_pct(ticker, asset_type, hours=24)
            change = seen_ticker_prices[ticker]

            if change is None:
                continue

            hit = change > 0  # bullish signal was correct if price went up
            entry = scores.setdefault(handle, {"hits": 0, "total": 0})
            entry["total"] += 1
            if hit:
                entry["hits"] += 1

        result = [
            {
                "handle": h,
                "hit_rate": v["hits"] / v["total"],
                "hits": v["hits"],
                "total": v["total"],
            }
            for h, v in scores.items()
            if v["total"] >= 2
        ]
        return sorted(result, key=lambda x: x["hit_rate"], reverse=True)
