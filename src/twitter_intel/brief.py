import logging
import os
from datetime import date
from pathlib import Path

import requests
import yfinance as yf

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)

_MIN_SIGNALS = 5          # target at least this many tickers per brief
_LOOKBACK_STEPS = [24, 48, 72, 120]  # expand window until we have enough signals


def _fetch_price(ticker: str) -> float | None:
    try:
        hist = yf.Ticker(ticker).history(period="1d", interval="5m")
        return float(hist["Close"].iloc[-1]) if not hist.empty else None
    except Exception:
        return None


def _dedup_ta_notes(raw: str | None) -> str:
    """Deduplicate TA notes joined with ||| separator, return top 2."""
    if not raw:
        return ""
    seen: set = set()
    unique = []
    for note in raw.split("|||"):
        note = note.strip()
        key = note.lower()[:20]
        if note and key not in seen:
            seen.add(key)
            unique.append(note)
    return " · ".join(unique[:2])


def _build_brief(signals: list, expert_scores: list) -> str:
    today = date.today().strftime("%b %d, %Y")
    lines = [f"📊 <b>Daily Trading Brief — {today}</b>\n"]

    if signals:
        lines.append("🏦 <b>Stocks to Watch</b>")
        for s in signals:
            ticker = s["ticker"]
            day = s.get("day_count") or 0
            swing = s.get("swing_count") or 0
            trade_label = "📅 Day" if day >= swing else "📆 Swing"
            n_experts = s["expert_count"]

            # Fetch live price
            price = _fetch_price(ticker)
            avg_target = s.get("avg_target")
            ta_notes = _dedup_ta_notes(s.get("all_ta_notes"))

            price_str = f"${price:.2f}" if price else "N/A"
            if price and avg_target and avg_target > price:
                gain_pct = (avg_target - price) / price * 100
                target_str = f"→ ${avg_target:.2f} (+{gain_pct:.1f}%)"
            elif avg_target:
                target_str = f"→ ${avg_target:.2f}"
            else:
                target_str = ""

            header = f"  🟢 <b>${ticker}</b> — {n_experts} expert(s) · {trade_label}"
            price_line = f"     Entry: {price_str}"
            if target_str:
                price_line += f"  Target: {target_str}"
            lines.append(header)
            lines.append(price_line)
            if ta_notes:
                lines.append(f"     <i>{ta_notes}</i>")
            lines.append("")
    else:
        lines.append("<i>No significant stock signals found in the last 5 days.</i>\n")

    # Expert P&L leaderboard
    if expert_scores:
        lines.append("🏆 <b>Expert Performance</b> <i>(simulated paper trades)</i>")
        for e in expert_scores[:5]:
            win_rate = int(e["win_rate"] * 100)
            avg_pnl = e["avg_pnl_pct"] * 100
            sign = "+" if avg_pnl >= 0 else ""
            bar = "▓" * (win_rate // 10) + "░" * (10 - win_rate // 10)
            lines.append(
                f"  @{e['handle']} {bar} {win_rate}% wins · "
                f"avg {sign}{avg_pnl:.1f}% · {e['total']} trades"
            )
        lines.append("")

    return "\n".join(lines)


class BriefGenerator:
    def __init__(
        self,
        store: TwitterIntelStore,
        lookback_hours: int = 24,
        min_expert_mentions: int = 1,
        scorer=None,
    ):
        self.store = store
        self.lookback_hours = lookback_hours
        self.min_expert_mentions = min_expert_mentions
        self.scorer = scorer

    def _get_signals(self) -> list:
        """Fetch signals, expanding lookback window until we have >= _MIN_SIGNALS tickers."""
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

        text = _build_brief(signals, expert_scores)

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
