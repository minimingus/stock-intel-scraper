from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path

import requests
import yfinance as yf

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)

_MIN_SIGNALS = 5
_price_cache: dict = {}


def _fetch_price(ticker: str) -> float | None:
    if ticker in _price_cache:
        return _price_cache[ticker]
    try:
        hist = yf.Ticker(ticker).history(period="1d", interval="5m")
        if not hist.empty:
            price = float(hist["Close"].iloc[-1])
            _price_cache[ticker] = price
            return price
    except Exception:
        pass
    return None
_LOOKBACK_STEPS = [24, 48, 72, 120]


def _signal_age_label(latest_signal_time: str | None, trade_type: str) -> str:
    if not latest_signal_time:
        return ""
    try:
        posted = datetime.fromisoformat(latest_signal_time)
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - posted).total_seconds() / 3600
        stale_threshold = 4 if trade_type == "day" else 48
        age_str = f"{int(age_hours)}h ago" if age_hours < 24 else f"{age_hours/24:.1f}d ago"
        stale = age_hours > stale_threshold
        return f"{'⚠️ Stale · ' if stale else ''}{age_str}"
    except Exception:
        return ""


def _is_qualified(e: dict, min_trades: int, min_win_rate: float) -> bool:
    return (
        e["total"] >= min_trades
        and e["win_rate"] >= min_win_rate
        and e.get("expectancy", 0) > 0
    )


def _build_brief(
    signals: list,
    expert_scores: list,
    store: TwitterIntelStore,
    min_trades: int = 5,
    min_win_rate: float = 0.50,
) -> str:
    today = date.today().strftime("%b %d, %Y")
    lines = [f"📊 <b>Daily Trading Brief — {today}</b>\n"]

    # Build expert lookup (handle -> score dict)
    expert_map = {e["handle"]: e for e in expert_scores}

    # Qualify experts
    qualified = [e for e in expert_scores if _is_qualified(e, min_trades, min_win_rate)]
    qualified.sort(key=lambda e: e.get("adjusted_expectancy", e["expectancy"]), reverse=True)

    # ── Section 1: TOP EXPERTS ──────────────────────────────────────────────
    lines.append("=== TOP EXPERTS ===")
    if qualified:
        for rank, e in enumerate(qualified, 1):
            win_rate = int(e["win_rate"] * 100)
            avg_return = (e.get("adjusted_expectancy", e["expectancy"]) or 0) * 100
            sign = "+" if avg_return >= 0 else ""
            lines.append(
                f"{rank}. @{e['handle']}   {sign}{avg_return:.1f}%/trade  "
                f"{win_rate}% wins  {e['total']} trades"
            )
            recent = store.get_expert_recent_trades(e["handle"], limit=5)
            if recent:
                trade_parts = []
                for t in recent:
                    pnl = (t["pnl_pct"] or 0) * 100
                    icon = "✓" if t["outcome"] == "win" else "✗"
                    trade_parts.append(f"{t['ticker']} {pnl:+.1f}% {icon}")
                lines.append(f"   Recent: {'  '.join(trade_parts)}")
            lines.append("")
    else:
        lines.append("<i>No qualified experts yet — need ≥{} closed trades and ≥{}% win rate.</i>".format(
            min_trades, int(min_win_rate * 100)
        ))
        lines.append("")

    # ── Section 2: SIGNALS TO WATCH ────────────────────────────────────────
    lines.append("=== SIGNALS TO WATCH ===")

    qualified_handles = {e["handle"] for e in qualified}

    # Filter signals: at least one calling expert must be qualified
    watchlist = []
    for s in signals:
        handles = [h.strip() for h in (s.get("experts") or "").split(",") if h.strip()]
        callers = [h for h in handles if h in qualified_handles]
        if callers:
            watchlist.append((s, callers))

    if watchlist:
        for s, callers in watchlist:
            ticker = s["ticker"]
            day = s.get("day_count") or 0
            swing = s.get("swing_count") or 0
            trade_type = "day" if day >= swing else "swing"

            age_str = _signal_age_label(s.get("latest_signal_time"), trade_type)

            caller_parts = []
            for h in callers:
                e = expert_map.get(h, {})
                avg_ret = (e.get("adjusted_expectancy", e.get("expectancy", 0)) or 0) * 100
                wr = int((e.get("win_rate", 0) or 0) * 100)
                sign = "+" if avg_ret >= 0 else ""
                caller_parts.append(f"@{h} ({sign}{avg_ret:.1f}%/trade, {wr}% wins)")

            callers_str = ", ".join(caller_parts)

            avg_target = s.get("avg_target")
            entry = _fetch_price(ticker)
            entry_str = f"${entry:.2f}" if entry else "market"
            target_str = ""
            if avg_target and entry and avg_target > entry:
                gain_pct = (avg_target - entry) / entry * 100
                target_str = f"  Target: ${avg_target:.2f} (+{gain_pct:.1f}%)"

            # Expert-specified stop + R:R (only when from tweet, not ATR default)
            stop_str = ""
            rr_str = ""
            expert_stop = s.get("expert_stop")
            if expert_stop and entry:
                stop_str = f"  Stop: ${expert_stop:.2f}"
                if avg_target and avg_target > entry and entry > expert_stop:
                    rr = (avg_target - entry) / (entry - expert_stop)
                    rr_str = f"  R:R 1:{rr:.1f}"

            lines.append(f"${ticker}  by {callers_str}")
            price_line = f"  Entry: {entry_str}{target_str}{stop_str}{rr_str}"
            if age_str:
                price_line += f"  |  Called {age_str}"
            lines.append(price_line)
            lines.append("")
    else:
        lines.append("<i>No signals from proven experts.</i>")
        lines.append("")

    return "\n".join(lines)


class BriefGenerator:
    def __init__(
        self,
        store: TwitterIntelStore,
        lookback_hours: int = 24,
        min_expert_mentions: int = 1,
        scorer=None,
        min_trades: int = 5,
        min_win_rate: float = 0.50,
    ):
        self.store = store
        self.lookback_hours = lookback_hours
        self.min_expert_mentions = min_expert_mentions
        self.scorer = scorer
        self.min_trades = min_trades
        self.min_win_rate = min_win_rate

    def _get_signals(self) -> list:
        for hours in _LOOKBACK_STEPS:
            signals = self.store.get_stock_signals_for_brief(
                lookback_hours=hours,
                min_expert_mentions=self.min_expert_mentions,
            )
            if len(signals) >= _MIN_SIGNALS or hours == _LOOKBACK_STEPS[-1]:
                logger.info(
                    "Brief: found %d stock signals in last %dh window", len(signals), hours
                )
                return signals
        return []

    def generate(self) -> str:
        signals = self._get_signals()

        expert_scores = []
        if self.scorer:
            try:
                expert_scores = self.scorer.score()
            except Exception as e:
                logger.warning("Expert scoring failed: %s", e)

        _price_cache.clear()
        text = _build_brief(
            signals, expert_scores, self.store,
            min_trades=self.min_trades,
            min_win_rate=self.min_win_rate,
        )

        # Portfolio summary
        summary = self.store.get_portfolio_summary()
        if summary.get("total"):
            cumulative = (summary.get("avg_pnl_pct") or 0) * 100
            sign = "+" if cumulative >= 0 else ""
            text += (
                f"\n📈 <b>Portfolio:</b> {summary['total']} trades · "
                f"{summary.get('wins', 0)}W/{summary.get('losses', 0)}L/"
                f"{summary.get('expired', 0)}E · avg {sign}{cumulative:.1f}% per trade"
            )

        expert_count = self.store.get_expert_count()
        tweet_count = self.store.get_tweet_count_24h()
        text += f"\n📡 <i>Monitoring {expert_count} accounts · {tweet_count} tweets analyzed</i>"
        return text

    def send(self):
        brief = None
        try:
            brief = self.generate()
            token = os.environ["TELEGRAM_BOT_TOKEN"]
            chat_id = os.environ["TELEGRAM_CHAT_ID"]
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": brief, "parse_mode": "HTML"},
                timeout=10,
            )
            resp.raise_for_status()
            logger.info("Daily brief sent via Telegram (%d chars)", len(brief))
        except Exception as e:
            logger.error("Send failed: %s — saving to file", e)
            path = Path(f"logs/brief-{date.today()}.txt")
            path.parent.mkdir(exist_ok=True)
            path.write_text(brief or f"Brief generation failed: {e}")
            logger.info("Brief saved to %s", path)
