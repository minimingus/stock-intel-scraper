from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from .hype_aggregator import aggregate_hype, filter_penny_pumps
from .store import TwitterIntelStore

logger = logging.getLogger(__name__)


def _build_brief(
    pennies: list[dict],
    stocks: list[dict],
    expert_count: int,
    tweet_count: int,
) -> str:
    today = date.today().strftime("%b %d")
    lines = [f"📈 <b>MOST HYPED — {today}</b>", "━" * 20]

    if stocks:
        for rank, item in enumerate(stocks, 1):
            handles_str = " ".join(f"@{h}" for h in item["handles"])
            lines.append(f"{rank}. ${item['ticker']}  ×{item['count']}  {handles_str}")
    else:
        lines.append("<i>No signals in the last 48h.</i>")

    lines += ["", "🎰 <b>PENNY PUMP WATCH</b>", "━" * 20]

    _il = ZoneInfo("Asia/Jerusalem")
    if pennies:
        for item in pennies:
            price  = item.get("price")
            mktcap = item.get("mktcap")
            price_str  = f"${price:.2f}" if price is not None else "?"
            mktcap_str = f"cap ${mktcap // 1_000_000}M" if mktcap else ""
            time_str = ""
            raw_t = item.get("latest_time")
            if raw_t:
                try:
                    dt = datetime.fromisoformat(raw_t.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    time_str = f"  🕐 {dt.astimezone(_il).strftime('%H:%M IL')}"
                except Exception:
                    pass
            lines.append(f"${item['ticker']}  ×{item['count']}  {price_str}  {mktcap_str}{time_str}")
    else:
        lines.append("<i>No penny activity.</i>")

    lines.append(
        f"\n📡 <i>Monitoring {expert_count} accounts · {tweet_count} tweets analyzed</i>"
    )
    return "\n".join(lines)


class BriefGenerator:
    def __init__(
        self,
        store: TwitterIntelStore,
        lookback_hours: int = 48,
        fetcher=None,
    ):
        self.store = store
        self.lookback_hours = lookback_hours
        self._fetcher = fetcher  # injectable for tests; None = use yfinance default

    def generate(self) -> str:
        mentions = self.store.get_hype_mentions(lookback_hours=self.lookback_hours)
        hype     = aggregate_hype(mentions)

        kwargs = {"fetcher": self._fetcher} if self._fetcher else {}
        pennies, stocks = filter_penny_pumps(hype, **kwargs)

        expert_count = self.store.get_expert_count()
        tweet_count  = self.store.get_tweet_count_24h()

        return _build_brief(pennies, stocks, expert_count, tweet_count)

    def send(self):
        brief = None
        try:
            brief = self.generate()
            token   = os.environ["TELEGRAM_BOT_TOKEN"]
            chat_id = os.environ["TELEGRAM_CHAT_ID"]
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": brief, "parse_mode": "HTML"},
                timeout=10,
            )
            resp.raise_for_status()
            logger.info("Brief sent (%d chars)", len(brief))
        except Exception as e:
            logger.error("Send failed: %s — saving to file", e)
            path = Path(f"logs/brief-{date.today()}.txt")
            path.parent.mkdir(exist_ok=True)
            path.write_text(brief or f"Brief generation failed: {e}")
