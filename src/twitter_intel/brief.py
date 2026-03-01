import json
import logging
import os
from datetime import date
from pathlib import Path

import requests
from anthropic import Anthropic

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)

_SYNTHESIS_PROMPT = """\
You are a professional trading analyst. Based on these signals from expert traders on Twitter \
(ranked by number of distinct experts who mentioned each asset), write a concise daily trading brief.

Signals:
{signals_json}

Write a brief with up to 3 entries per section (skip sections with no data):
  🏦 *Stocks to Watch*
  🪙 *Crypto Signals*
  🎯 *Polymarket Attention*

For each entry include: the ticker, expert count, dominant sentiment, and a one-line insight.
Use Telegram Markdown (* bold, _ italic). Start with: 📊 *Daily Trading Brief — {date}*
Return only the formatted message, no extra commentary."""


class BriefGenerator:
    def __init__(
        self,
        store: TwitterIntelStore,
        lookback_hours: int = 24,
        min_expert_mentions: int = 2,
    ):
        self.store = store
        self.lookback_hours = lookback_hours
        self.min_expert_mentions = min_expert_mentions
        self.client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def generate(self) -> str:
        signals = self.store.get_signals_for_brief(
            lookback_hours=self.lookback_hours,
            min_expert_mentions=self.min_expert_mentions,
        )

        if not signals:
            text = (
                f"📊 *Daily Trading Brief — {date.today().strftime('%b %d, %Y')}*\n\n"
                f"_No significant signals today "
                f"(need \u2265{self.min_expert_mentions} expert mentions per asset)._"
            )
        else:
            msg = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": _SYNTHESIS_PROMPT.format(
                        signals_json=json.dumps(signals, ensure_ascii=False, indent=2),
                        date=date.today().strftime("%b %d, %Y"),
                    ),
                }],
            )
            text = msg.content[0].text.strip()

        expert_count = self.store.get_expert_count()
        tweet_count = self.store.get_tweet_count_24h()
        text += f"\n\n📡 _Monitoring {expert_count} accounts \u00b7 {tweet_count} tweets analyzed_"
        return text

    def send(self):
        brief = self.generate()
        try:
            token = os.environ["TELEGRAM_BOT_TOKEN"]
            chat_id = os.environ["TELEGRAM_CHAT_ID"]
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": brief, "parse_mode": "Markdown"},
                timeout=10,
            )
            resp.raise_for_status()
            logger.info("Daily brief sent via Telegram (%d chars)", len(brief))
        except Exception as e:
            logger.error("Telegram send failed: %s — saving to file", e)
            path = Path(f"logs/brief-{date.today()}.txt")
            path.parent.mkdir(exist_ok=True)
            path.write_text(brief)
            logger.info("Brief saved to %s", path)
