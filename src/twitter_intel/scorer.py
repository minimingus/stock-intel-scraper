import logging
from datetime import datetime, timedelta, timezone

import yfinance as yf

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)

# Cache: (symbol, date_str) -> hourly history DataFrame
_hist_cache: dict = {}


def _get_price_at(symbol: str, at: datetime) -> float | None:
    """Return closing price for `symbol` at the given UTC datetime."""
    date_key = at.strftime("%Y-%m-%d")
    cache_key = (symbol, date_key)

    if cache_key not in _hist_cache:
        try:
            _hist_cache[cache_key] = yf.Ticker(symbol).history(
                period="8d", interval="1h", auto_adjust=True
            )
        except Exception as e:
            logger.debug("History fetch failed for %s: %s", symbol, e)
            _hist_cache[cache_key] = None

    hist = _hist_cache[cache_key]
    if hist is None or hist.empty:
        return None

    # Find the nearest bar at or before `at`
    try:
        hist_utc = hist.copy()
        hist_utc.index = hist_utc.index.tz_convert("UTC")
        past = hist_utc[hist_utc.index <= at]
        if past.empty:
            return None
        return float(past["Close"].iloc[-1])
    except Exception as e:
        logger.debug("Price lookup error for %s at %s: %s", symbol, at, e)
        return None


def _symbol(ticker: str, asset_type: str) -> str:
    return f"{ticker}-USD" if asset_type == "crypto" else ticker


class ExpertScorer:
    def __init__(self, store: TwitterIntelStore, lookback_hours: int = 168):
        self.store = store
        self.lookback_hours = lookback_hours

    def score(self) -> list[dict]:
        """
        Score each expert by comparing price at tweet time vs price 24h later.
        A bullish signal is a HIT if price rose at least 0.5% within 24h of posting.
        Only experts with >= 3 scored signals are ranked.
        Returns list of {handle, hit_rate, hits, total} sorted by hit_rate desc.
        """
        signals = self.store.get_signals_with_handles(self.lookback_hours)
        if not signals:
            return []

        now = datetime.now(timezone.utc)
        scores: dict[str, dict] = {}

        for sig in signals:
            handle = sig["handle"]
            ticker = sig["ticker"]
            asset_type = sig["asset_type"]
            scraped_at = sig["scraped_at"]

            # Parse signal time
            try:
                post_time = datetime.fromisoformat(scraped_at)
                if post_time.tzinfo is None:
                    post_time = post_time.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            # Need at least 24h to have elapsed since the post
            check_time = post_time + timedelta(hours=24)
            if check_time > now:
                continue  # too recent to score

            sym = _symbol(ticker, asset_type)
            price_at_post = _get_price_at(sym, post_time)
            price_24h_later = _get_price_at(sym, check_time)

            if price_at_post is None or price_24h_later is None or price_at_post == 0:
                continue

            change_pct = (price_24h_later - price_at_post) / price_at_post * 100
            hit = change_pct >= 0.5  # bullish signal correct if price up >= 0.5%

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
            if v["total"] >= 3
        ]
        return sorted(result, key=lambda x: x["hit_rate"], reverse=True)
