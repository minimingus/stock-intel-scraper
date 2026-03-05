import logging
import os
from datetime import date
from pathlib import Path

import requests

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)

_SECTION_ICONS = {
    "stock": "🏦",
    "crypto": "🪙",
    "polymarket": "🎯",
}
_SECTION_LABELS = {
    "stock": "Stocks to Watch",
    "crypto": "Crypto Signals",
    "polymarket": "Polymarket Attention",
}


def _build_brief(signals: list, min_expert_mentions: int, expert_scores: list) -> str:
    today = date.today().strftime("%b %d, %Y")
    lines = [f"📊 <b>Daily Trading Brief — {today}</b>\n"]

    by_type: dict[str, list] = {}
    for s in signals:
        by_type.setdefault(s["asset_type"], []).append(s)

    limits = {"stock": 5, "crypto": 3, "polymarket": 3}
    for asset_type in ("stock", "crypto", "polymarket"):
        items = by_type.get(asset_type, [])[:limits[asset_type]]
        if not items:
            continue
        icon = _SECTION_ICONS[asset_type]
        label = _SECTION_LABELS[asset_type]
        lines.append(f"{icon} <b>{label}</b>")
        for s in items:
            day = s.get("day_count") or 0
            swing = s.get("swing_count") or 0
            trade_label = "📅 Day" if day >= swing else "📆 Swing"
            lines.append(
                f"  🟢 <b>${s['ticker']}</b> — {s['expert_count']} expert(s) · {trade_label}"
            )
        lines.append("")

    if len(lines) == 1:
        lines.append(
            f"<i>No significant signals today "
            f"(need \u2265{min_expert_mentions} expert mentions per asset).</i>"
        )
        lines.append("")

    # Expert accuracy ranking
    if expert_scores:
        lines.append("🏆 <b>Expert Accuracy</b> <i>(price 24h after post)</i>")
        for e in expert_scores[:5]:
            pct = int(e["hit_rate"] * 100)
            bar = "▓" * (pct // 10) + "░" * (10 - pct // 10)
            lines.append(
                f"  @{e['handle']} {bar} {pct}% ({e['hits']}/{e['total']})"
            )
        lines.append("")

    return "\n".join(lines)


class BriefGenerator:
    def __init__(
        self,
        store: TwitterIntelStore,
        lookback_hours: int = 24,
        min_expert_mentions: int = 2,
        scorer=None,
    ):
        self.store = store
        self.lookback_hours = lookback_hours
        self.min_expert_mentions = min_expert_mentions
        self.scorer = scorer

    def generate(self) -> str:
        signals = self.store.get_signals_for_brief(
            lookback_hours=self.lookback_hours,
            min_expert_mentions=self.min_expert_mentions,
        )

        expert_scores = []
        if self.scorer:
            try:
                expert_scores = self.scorer.score()
            except Exception as e:
                logger.warning("Expert scoring failed: %s", e)

        text = _build_brief(signals, self.min_expert_mentions, expert_scores)

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
