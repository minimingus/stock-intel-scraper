import logging
from datetime import datetime, timedelta, timezone

import yfinance as yf

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)

_hist_cache: dict = {}
_HIT_THRESHOLD = 0.10   # 10% price increase required
_WINDOW_HOURS = 48       # look at max price within 48h after post


def _get_history(symbol: str) -> object:
    if symbol not in _hist_cache:
        try:
            _hist_cache[symbol] = yf.Ticker(symbol).history(
                period="60d", interval="1h", auto_adjust=True
            )
        except Exception as e:
            logger.debug("History fetch failed for %s: %s", symbol, e)
            _hist_cache[symbol] = None
    return _hist_cache[symbol]


def _price_at(hist, at: datetime) -> float | None:
    """Closing price at or just before `at`."""
    if hist is None or hist.empty:
        return None
    try:
        utc = hist.copy()
        utc.index = utc.index.tz_convert("UTC")
        past = utc[utc.index <= at]
        return float(past["Close"].iloc[-1]) if not past.empty else None
    except Exception:
        return None


def _max_price_in_window(hist, start: datetime, hours: int) -> float | None:
    """Max closing price in (start, start+hours]."""
    if hist is None or hist.empty:
        return None
    try:
        utc = hist.copy()
        utc.index = utc.index.tz_convert("UTC")
        end = start + timedelta(hours=hours)
        window = utc[(utc.index > start) & (utc.index <= end)]
        return float(window["Close"].max()) if not window.empty else None
    except Exception:
        return None


def _symbol(ticker: str, asset_type: str) -> str:
    return f"{ticker}-USD" if asset_type == "crypto" else ticker


class ExpertScorer:
    def __init__(self, store: TwitterIntelStore, lookback_hours: int = 168):
        self.store = store
        self.lookback_hours = lookback_hours

    def score(self) -> list[dict]:
        """
        Backtest each expert: for every bullish signal, check if the stock
        rose >= 10% within 48h of the post. Requires >= 3 scored signals.
        Returns list sorted by hit_rate desc.
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
            post_time_str = sig["post_time"]

            try:
                post_time = datetime.fromisoformat(post_time_str)
                if post_time.tzinfo is None:
                    post_time = post_time.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            # Must have 48h elapsed to evaluate
            if post_time + timedelta(hours=_WINDOW_HOURS) > now:
                continue

            sym = _symbol(ticker, asset_type)
            hist = _get_history(sym)

            base_price = _price_at(hist, post_time)
            max_price = _max_price_in_window(hist, post_time, _WINDOW_HOURS)

            if base_price is None or max_price is None or base_price == 0:
                continue

            gain = (max_price - base_price) / base_price
            hit = gain >= _HIT_THRESHOLD

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
