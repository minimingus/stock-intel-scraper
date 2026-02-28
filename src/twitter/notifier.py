import os
from datetime import datetime

import requests

TOPIC_EMOJIS = {
    "new_release": "📦",
    "research": "🔬",
    "devtools": "🛠",
    "tools": "🔧",
    "community": "💬",
}
TOPIC_LABELS = {
    "new_release": "New Releases",
    "research": "Research",
    "devtools": "Dev Tools",
    "tools": "Tools & Products",
    "community": "Community",
}


class TelegramNotifier:
    def __init__(self, bot_token: str | None = None, chat_id: str | None = None):
        self._token = bot_token or os.environ["TELEGRAM_BOT_TOKEN"]
        self._chat_id = chat_id or os.environ["TELEGRAM_CHAT_ID"]

    def _send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        requests.post(
            url,
            json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )

    def send_digest(
        self, signals: list[dict], window_start: datetime, window_end: datetime
    ) -> None:
        if not signals:
            return
        start_str = window_start.strftime("%H:%M")
        end_str = window_end.strftime("%H:%M")
        lines = [f"<b>🤖 AI Pulse — {start_str}–{end_str} UTC</b>\n"]
        for sig in signals:
            emoji = TOPIC_EMOJIS.get(sig["topic"], "•")
            label = TOPIC_LABELS.get(sig["topic"], sig["topic"].replace("_", " ").title())
            lines.append(f"<b>{emoji} {label}</b>")
            lines.append(sig["summary"])
            lines.append("")
        sources = sorted({f"@{tw['author']}" for sig in signals for tw in sig.get("tweets", [])})
        if sources:
            lines.append(f"<i>Sources: {', '.join(sources)}</i>")
        self._send("\n".join(lines))

    def send_daily_brief(self, synthesis: str, date: datetime) -> None:
        date_str = date.strftime("%B %d, %Y")
        self._send(f"<b>📰 Daily AI Brief — {date_str}</b>\n\n{synthesis}")
