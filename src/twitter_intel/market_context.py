import logging
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_SPY_BEAR_THRESHOLD = -0.015   # -1.5% = warning
_SPY_BULL_THRESHOLD = +0.005   # +0.5% = green


_spy_cache: dict = {}


def spy_regime() -> dict:
    """Return SPY's daily % change and a regime label: 'bull', 'bear', or 'neutral'."""
    if _spy_cache:
        return _spy_cache.copy()
    _neutral = {"change_pct": 0.0, "regime": "neutral"}
    try:
        hist = yf.Ticker("SPY").history(period="5d", interval="1d", auto_adjust=True)
        if len(hist) < 2:
            return _neutral.copy()
        prev_close = float(hist["Close"].iloc[-2])
        last_close = float(hist["Close"].iloc[-1])
        change_pct = (last_close - prev_close) / prev_close
        if change_pct <= _SPY_BEAR_THRESHOLD:
            regime = "bear"
        elif change_pct >= _SPY_BULL_THRESHOLD:
            regime = "bull"
        else:
            regime = "neutral"
        result = {"change_pct": change_pct, "regime": regime}
        _spy_cache.update(result)
        return result.copy()
    except Exception as e:
        logger.debug("SPY fetch failed: %s", e)
        return _neutral.copy()


_ticker_cache: dict = {}


def ticker_context(ticker: str) -> dict:
    """
    Return intraday context for a ticker:
      - change_pct: today's % change vs previous close
      - volume_ratio: today's volume vs 20-day average
    """
    ticker = ticker.upper().strip()
    if ticker in _ticker_cache:
        return _ticker_cache[ticker].copy()
    result = {"change_pct": None, "volume_ratio": None}
    try:
        t = yf.Ticker(ticker)
        # Today's intraday
        intraday = t.history(period="1d", interval="5m", auto_adjust=True)
        # 20-day daily for volume avg
        daily = t.history(period="25d", interval="1d", auto_adjust=True)

        if not intraday.empty and len(daily) >= 2:
            # Determine prev_close robustly regardless of market hours
            last_daily_date = daily.index[-1].date()
            today_date = pd.Timestamp.now(tz=daily.index.tz if daily.index.tz else "UTC").date()
            prev_close_idx = -2 if last_daily_date == today_date else -1
            prev_close = float(daily["Close"].iloc[prev_close_idx])
            last_price = float(intraday["Close"].iloc[-1])
            result["change_pct"] = (last_price - prev_close) / prev_close

        if len(daily) >= 20:
            avg_vol = float(daily["Volume"].iloc[:-1].tail(20).mean())
            today_vol = float(daily["Volume"].iloc[-1])
            if avg_vol > 0:
                result["volume_ratio"] = today_vol / avg_vol
    except Exception as e:
        logger.debug("Context fetch failed for %s: %s", ticker, e)

    _ticker_cache[ticker] = result
    return result.copy()


_SENTIMENT_CACHE: dict = {}
_VIX_FEAR_THRESHOLD = 25.0
_VIX_CALM_THRESHOLD = 15.0
_SENTIMENT_BEAR_THRESHOLD = -0.01  # -1% per index = bear signal


def market_sentiment() -> dict:
    """
    Composite market sentiment from SPY, QQQ, and VIX.
    Returns:
        spy_change: SPY daily % change
        qqq_change: QQQ daily % change
        vix: current VIX level
        regime: 'bull' | 'bear' | 'neutral'
        sentiment_score: float in [-1.0, +1.0], positive = bullish
        warning: str | None — human-readable caution message if bearish
    """
    if _SENTIMENT_CACHE:
        return _SENTIMENT_CACHE.copy()

    def _pct_change(ticker: str) -> float | None:
        try:
            hist = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=True)
            if len(hist) < 2:
                return None
            prev = float(hist["Close"].iloc[-2])
            last = float(hist["Close"].iloc[-1])
            return (last - prev) / prev
        except Exception:
            return None

    def _vix() -> float | None:
        try:
            hist = yf.Ticker("^VIX").history(period="2d", interval="1d")
            if hist.empty:
                return None
            return float(hist["Close"].iloc[-1])
        except Exception:
            return None

    spy = _pct_change("SPY")
    qqq = _pct_change("QQQ")
    vix = _vix()

    # Score components (each in [-1, +1] range)
    spy_score = max(-1.0, min(1.0, (spy or 0) / 0.02))    # ±2% = ±1.0
    qqq_score = max(-1.0, min(1.0, (qqq or 0) / 0.02))
    vix_score = 0.0
    if vix is not None:
        if vix >= _VIX_FEAR_THRESHOLD:
            vix_score = -min(1.0, (vix - _VIX_FEAR_THRESHOLD) / 15.0)
        elif vix <= _VIX_CALM_THRESHOLD:
            vix_score = +min(0.3, (_VIX_CALM_THRESHOLD - vix) / 10.0)

    sentiment_score = round((spy_score * 0.4 + qqq_score * 0.4 + vix_score * 0.2), 3)

    # Regime determination
    bear_conditions = (
        (spy is not None and spy <= _SENTIMENT_BEAR_THRESHOLD) or
        (qqq is not None and qqq <= _SENTIMENT_BEAR_THRESHOLD) or
        (vix is not None and vix >= _VIX_FEAR_THRESHOLD)
    )
    bull_conditions = (
        (spy is not None and spy >= 0.005) and
        (qqq is not None and qqq >= 0.005) and
        (vix is None or vix < _VIX_FEAR_THRESHOLD)
    )

    if bear_conditions:
        regime = "bear"
    elif bull_conditions:
        regime = "bull"
    else:
        regime = "neutral"

    # Warning message
    warning_parts = []
    if spy is not None and spy <= _SENTIMENT_BEAR_THRESHOLD:
        warning_parts.append(f"SPY {spy*100:+.1f}%")
    if qqq is not None and qqq <= _SENTIMENT_BEAR_THRESHOLD:
        warning_parts.append(f"QQQ {qqq*100:+.1f}%")
    if vix is not None and vix >= _VIX_FEAR_THRESHOLD:
        warning_parts.append(f"VIX {vix:.0f}")
    warning = "Market weakness: " + " · ".join(warning_parts) + " — tighten stops" if warning_parts else None

    result = {
        "spy_change": spy,
        "qqq_change": qqq,
        "vix": vix,
        "regime": regime,
        "sentiment_score": sentiment_score,
        "warning": warning,
    }
    _SENTIMENT_CACHE.update(result)
    return result.copy()


def clear_cache():
    _spy_cache.clear()
    _ticker_cache.clear()
    _SENTIMENT_CACHE.clear()
