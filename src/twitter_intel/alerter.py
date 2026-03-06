import logging
import os
from datetime import datetime, timezone

import requests

from .store import TwitterIntelStore
from . import market_context as mctx

logger = logging.getLogger(__name__)

_CONVERGENCE_WINDOW_MIN = 30
_CONVERGENCE_MIN_EXPERTS = 2
_PROVEN_MIN_TRADES = 5
_PROVEN_MIN_EXPECTANCY = 0.0
_ALERT_COOLDOWN_HOURS = 4


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
        if not e or e["total"] < _PROVEN_MIN_TRADES or e["expectancy"] <= _PROVEN_MIN_EXPECTANCY:
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
