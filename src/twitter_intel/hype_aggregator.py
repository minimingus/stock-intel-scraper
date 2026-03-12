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
        info = yf.Ticker(ticker).info
        price  = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
        mktcap = info.get("marketCap") or 0
        return {"price": float(price), "mktcap": int(mktcap)}
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

        enriched = {**item, "price": price, "mktcap": mktcap}

        if (
            price  is not None and price  < _PENNY_MAX_PRICE
            and mktcap is not None and mktcap < _PENNY_MAX_MKTCAP
            and mktcap > 0
        ):
            pennies.append(enriched)
        else:
            mainstream.append(enriched)

    return pennies[:top_pennies], mainstream[:top_stocks]
