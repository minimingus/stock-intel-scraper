from __future__ import annotations

import logging

import yfinance as yf

logger = logging.getLogger(__name__)

_PENNY_MAX_PRICE  = 5.0
_PENNY_MAX_MKTCAP = 100_000_000  # $100M


def aggregate_hype(mentions: list[dict]) -> list[dict]:
    """
    Collapse raw mention rows into per-ticker counts.
    Each handle is counted once per ticker (deduplication).
    Tracks latest_time (most recent tweet_time) per ticker.
    Returns list sorted by count desc.
    """
    seen: dict[str, set[str]] = {}       # ticker -> set of handles
    latest: dict[str, str | None] = {}   # ticker -> most recent tweet_time

    for row in mentions:
        ticker = row["ticker"]
        handle = row["handle"]
        t      = row.get("tweet_time")
        seen.setdefault(ticker, set()).add(handle)
        if t and (ticker not in latest or t > latest[ticker]):
            latest[ticker] = t

    result = [
        {
            "ticker":      ticker,
            "count":       len(handles),
            "handles":     sorted(handles),
            "latest_time": latest.get(ticker),
        }
        for ticker, handles in seen.items()
    ]
    result.sort(key=lambda r: r["count"], reverse=True)
    return result


def _default_fetcher(ticker: str) -> dict:
    try:
        tk   = yf.Ticker(ticker)
        info = tk.info

        price  = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
        mktcap = info.get("marketCap") or 0

        # Pre-market vs prior close
        premarket_pct: float | None = None
        pm_price  = info.get("preMarketPrice")
        prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
        if pm_price and prev_close:
            premarket_pct = (pm_price - prev_close) / prev_close * 100

        # Intraday: 12h change, momentum, volume ratio
        change_12h_pct: float | None = None
        momentum:       str   | None = None
        volume_ratio:   float | None = None

        hist = tk.history(period="2d", interval="1h")
        if not hist.empty and len(hist) >= 2:
            lookback   = min(12, len(hist) - 1)
            price_now  = float(hist["Close"].iloc[-1])
            price_back = float(hist["Close"].iloc[-(lookback + 1)])
            if price_back > 0:
                change_12h_pct = (price_now - price_back) / price_back * 100

            n        = min(3, len(hist))
            momentum = "↑" if hist["Close"].iloc[-1] > hist["Close"].iloc[-n] else "↓"

            avg_vol   = info.get("averageVolume") or info.get("averageDailyVolume10Day")
            today_vol = float(hist["Volume"].iloc[-12:].sum())
            if avg_vol and avg_vol > 0:
                volume_ratio = today_vol / avg_vol

        return {
            "price":         float(price),
            "mktcap":        int(mktcap),
            "change_12h_pct": change_12h_pct,
            "momentum":      momentum,
            "volume_ratio":  volume_ratio,
            "premarket_pct": premarket_pct,
        }
    except Exception:
        return {}


def filter_penny_pumps(
    hype: list[dict],
    top_stocks: int = 10,
    top_pennies: int = 5,
    fetcher=_default_fetcher,
) -> tuple[list[dict], list[dict]]:
    """
    Split hype list into (pennies, mainstream).
    Penny = price < $5 AND mktcap < $100M.
    Returns (penny_list[:top_pennies], mainstream_list[:top_stocks]).
    """
    pennies    = []
    mainstream = []

    for item in hype:
        info   = fetcher(item["ticker"])
        price  = info.get("price",  None)
        mktcap = info.get("mktcap", None)

        enriched = {
            **item,
            "price":          price,
            "mktcap":         mktcap,
            "change_12h_pct": info.get("change_12h_pct"),
            "momentum":       info.get("momentum"),
            "volume_ratio":   info.get("volume_ratio"),
            "premarket_pct":  info.get("premarket_pct"),
        }

        if (
            price  is not None and price  < _PENNY_MAX_PRICE
            and mktcap is not None and mktcap < _PENNY_MAX_MKTCAP
            and mktcap > 0
        ):
            pennies.append(enriched)
        else:
            mainstream.append(enriched)

    return pennies[:top_pennies], mainstream[:top_stocks]
