import logging
from functools import lru_cache
import yfinance as yf

logger = logging.getLogger(__name__)

_SPY_BEAR_THRESHOLD = -0.015   # -1.5% = warning
_SPY_BULL_THRESHOLD = +0.005   # +0.5% = green


@lru_cache(maxsize=1)
def spy_regime() -> dict:
    """Return SPY's daily % change and a regime label: 'bull', 'bear', or 'neutral'."""
    try:
        hist = yf.Ticker("SPY").history(period="2d", interval="1d", auto_adjust=True)
        if len(hist) < 2:
            return {"change_pct": 0.0, "regime": "neutral"}
        prev_close = float(hist["Close"].iloc[-2])
        last_close = float(hist["Close"].iloc[-1])
        change_pct = (last_close - prev_close) / prev_close
        if change_pct <= _SPY_BEAR_THRESHOLD:
            regime = "bear"
        elif change_pct >= _SPY_BULL_THRESHOLD:
            regime = "bull"
        else:
            regime = "neutral"
        return {"change_pct": change_pct, "regime": regime}
    except Exception as e:
        logger.debug("SPY fetch failed: %s", e)
        return {"change_pct": 0.0, "regime": "neutral"}


_ticker_cache: dict = {}


def ticker_context(ticker: str) -> dict:
    """
    Return intraday context for a ticker:
      - change_pct: today's % change vs previous close
      - volume_ratio: today's volume vs 20-day average
    """
    if ticker in _ticker_cache:
        return _ticker_cache[ticker]
    result = {"change_pct": None, "volume_ratio": None}
    try:
        t = yf.Ticker(ticker)
        # Today's intraday
        intraday = t.history(period="1d", interval="5m", auto_adjust=True)
        # 20-day daily for volume avg
        daily = t.history(period="25d", interval="1d", auto_adjust=True)

        if not intraday.empty and len(daily) >= 2:
            prev_close = float(daily["Close"].iloc[-2])
            last_price = float(intraday["Close"].iloc[-1])
            result["change_pct"] = (last_price - prev_close) / prev_close

        if len(daily) >= 20:
            avg_vol = float(daily["Volume"].iloc[-21:-1].mean())
            today_vol = float(daily["Volume"].iloc[-1])
            if avg_vol > 0:
                result["volume_ratio"] = today_vol / avg_vol
    except Exception as e:
        logger.debug("Context fetch failed for %s: %s", ticker, e)

    _ticker_cache[ticker] = result
    return result


def clear_cache():
    spy_regime.cache_clear()
    _ticker_cache.clear()
