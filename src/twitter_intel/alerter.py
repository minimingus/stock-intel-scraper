import logging
import os
from datetime import datetime, timezone

import requests
import yfinance as yf

from .store import TwitterIntelStore
from . import market_context as mctx

logger = logging.getLogger(__name__)

_CONVERGENCE_WINDOW_MIN = 30
_CONVERGENCE_MIN_EXPERTS = 2
_PROVEN_MIN_TRADES = 8
_PROVEN_MIN_EXPECTANCY = 0.0
_ALERT_COOLDOWN_HOURS = 4
_PUMP_COOLDOWN_HOURS = 2
_PUMP_MAX_PRICE = 10.0
_PUMP_MIN_VOL_RATIO = 5.0


def _format_alert(ticker: str, entries: list, store: TwitterIntelStore) -> str:
    """Format a Telegram alert message for a converging ticker."""
    expert_strs = [
        f"@{e['handle']} (E={e['expectancy']*100:+.1f}%, {e['total']} trades)"
        for e in entries
    ]
    ctx = mctx.ticker_context(ticker)
    sentiment = mctx.market_sentiment()

    lines = [f"🚨 <b>CONVERGENCE ALERT — ${ticker}</b>\n"]
    lines.append(f"<b>{len(entries)} proven experts in last {_CONVERGENCE_WINDOW_MIN}min:</b>")
    for s in expert_strs:
        lines.append(f"  {s}")
    lines.append("")

    if ctx["change_pct"] is not None:
        change = ctx["change_pct"] * 100
        vol = ctx["volume_ratio"]
        vol_str = f" · Vol {vol:.1f}× avg" if vol is not None else ""
        lines.append(f"Today: {change:+.1f}%{vol_str}")

    hist = store.get_ticker_paper_history(ticker)
    if hist and hist["total"]:
        avg_pnl = (hist["avg_pnl_pct"] or 0) * 100
        lines.append(
            f"History: {hist['total']} calls · {hist['wins']}W/{hist['losses']}L · "
            f"avg {avg_pnl:+.1f}%"
        )

    if sentiment["warning"]:
        lines.append(f"\n⚠️ {sentiment['warning']}")

    return "\n".join(lines)


def run_alert_check(store: TwitterIntelStore, scorer) -> int:
    """
    Check for high-confidence convergence signals in the last window.
    Sends Telegram alerts for new converging tickers. Returns count sent.
    """
    expert_scores = scorer.score() if scorer else []
    expert_map = {e["handle"]: e for e in expert_scores}

    # Get signals from last N minutes
    rows = store.conn.execute("""
        SELECT DISTINCT s.ticker, t.handle
        FROM signals s
        JOIN tweets t ON t.tweet_id = s.tweet_id
        WHERE s.sentiment = 'bullish'
          AND s.asset_type = 'stock'
          AND COALESCE(t.tweet_time, t.scraped_at) >= datetime('now', ?)
    """, (f"-{_CONVERGENCE_WINDOW_MIN} minutes",)).fetchall()

    # Group by ticker, filter to proven experts only
    by_ticker: dict[str, list] = {}
    for row in rows:
        handle = row["handle"]
        e = expert_map.get(handle)
        if not e or e["total"] < _PROVEN_MIN_TRADES or e.get("adjusted_expectancy", e["expectancy"]) <= _PROVEN_MIN_EXPECTANCY:
            continue
        by_ticker.setdefault(row["ticker"], []).append(e)

    # Alert on tickers with enough convergence
    sent = 0
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.warning("Telegram credentials missing, skipping alert")
        return 0

    mctx.clear_cache()
    for ticker, experts in by_ticker.items():
        if len(experts) < _CONVERGENCE_MIN_EXPERTS:
            continue
        if store.was_alert_sent_recently(ticker, _ALERT_COOLDOWN_HOURS):
            logger.info("Alert for %s suppressed (sent recently)", ticker)
            continue

        msg = _format_alert(ticker, experts, store)
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=10,
            )
            resp.raise_for_status()
            store.record_alert_sent(ticker, [e["handle"] for e in experts])
            logger.info("Alert sent for %s (%d experts)", ticker, len(experts))
            sent += 1
        except Exception as e:
            logger.error("Alert send failed for %s: %s", ticker, e)

    return sent


def _format_pump_alert(ticker: str, handles: list, price: float, ctx: dict) -> str:
    vol = ctx.get("volume_ratio")
    change = ctx.get("change_pct")
    vol_str = f"{vol:.1f}×" if vol is not None else "?"
    change_str = f"{change*100:+.1f}%" if change is not None else "?"
    handle_strs = " ".join(f"@{h}" for h in handles)
    return (
        f"🚨🚀 <b>PENNY PUMP ALERT — ${ticker}</b>\n\n"
        f"Price: <b>${price:.2f}</b> · Vol {vol_str} avg · Today: {change_str}\n"
        f"Mentioned by: {handle_strs}\n\n"
        f"<i>Low-float / penny pump pattern — high risk, fast moves</i>"
    )


def _fetch_price(ticker: str) -> float | None:
    try:
        hist = yf.Ticker(ticker).history(period="1d", interval="5m")
        return float(hist["Close"].iloc[-1]) if not hist.empty else None
    except Exception:
        return None


def run_penny_pump_check(store: TwitterIntelStore) -> int:
    """
    Detect penny stocks with explosive volume mentioned by any expert in the last 30 min.
    Sends an immediate Telegram alert with 2h cooldown. Returns count sent.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.warning("Telegram credentials missing, skipping pump alert")
        return 0

    rows = store.conn.execute("""
        SELECT DISTINCT s.ticker, t.handle
        FROM signals s
        JOIN tweets t ON t.tweet_id = s.tweet_id
        WHERE s.sentiment = 'bullish'
          AND s.asset_type = 'stock'
          AND COALESCE(t.tweet_time, t.scraped_at) >= datetime('now', ?)
    """, (f"-{_CONVERGENCE_WINDOW_MIN} minutes",)).fetchall()

    by_ticker: dict[str, list] = {}
    for row in rows:
        by_ticker.setdefault(row["ticker"], []).append(row["handle"])

    sent = 0
    for ticker, handles in by_ticker.items():
        if store.was_alert_sent_recently(ticker, _PUMP_COOLDOWN_HOURS):
            continue

        ctx = mctx.ticker_context(ticker)
        volume_ratio = ctx.get("volume_ratio")
        if volume_ratio is None or volume_ratio < _PUMP_MIN_VOL_RATIO:
            continue

        price = _fetch_price(ticker)
        if price is None or price >= _PUMP_MAX_PRICE:
            continue

        msg = _format_pump_alert(ticker, handles, price, ctx)
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=10,
            )
            resp.raise_for_status()
            store.record_alert_sent(ticker, handles)
            logger.info("Pump alert sent for %s @ $%.2f (vol %.1fx)", ticker, price, volume_ratio)
            sent += 1
        except Exception as e:
            logger.error("Pump alert send failed for %s: %s", ticker, e)

    mctx.clear_cache()
    return sent
