import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_PATH = Path("data/ai_signals.json")
SEEN_PATH = Path("data/seen_tweets.json")


class SignalStore:
    def __init__(self, signals_path: Path = DATA_PATH, seen_path: Path = SEEN_PATH):
        self._signals_path = signals_path
        self._seen_path = seen_path
        self._signals_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict]:
        if not self._signals_path.exists():
            return []
        return json.loads(self._signals_path.read_text())

    def _save(self, signals: list[dict]) -> None:
        self._signals_path.write_text(json.dumps(signals, indent=2))

    def append_signal(
        self, topic: str, summary: str, sources: list[str], relevance_score: float
    ) -> dict:
        signal = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "topic": topic,
            "summary": summary,
            "sources": sources,
            "relevance_score": relevance_score,
        }
        signals = self._load()
        signals.append(signal)
        self._save(signals)
        return signal

    def get_signals_since(self, hours: int) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [
            s for s in self._load()
            if datetime.fromisoformat(s["timestamp"]) > cutoff
        ]

    def prune_old(self, days: int = 7) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        signals = self._load()
        kept = [s for s in signals if datetime.fromisoformat(s["timestamp"]) > cutoff]
        removed = len(signals) - len(kept)
        self._save(kept)
        return removed

    def is_seen(self, tweet_id: str) -> bool:
        if not self._seen_path.exists():
            return False
        seen = json.loads(self._seen_path.read_text())
        return tweet_id in seen

    def mark_seen(self, tweet_ids: list[str]) -> None:
        seen: set[str] = set()
        if self._seen_path.exists():
            seen = set(json.loads(self._seen_path.read_text()))
        seen.update(tweet_ids)
        # cap at 10k to avoid unbounded growth
        self._seen_path.write_text(json.dumps(list(seen)[-10000:]))

    def get_recent_signals_context(self, hours: int = 6) -> str:
        """Return a formatted string of recent signals for injection into AI prompts."""
        signals = self.get_signals_since(hours=hours)
        if not signals:
            return ""
        lines = [f"Recent AI news context (last {hours}h):"]
        for s in signals:
            lines.append(f"- {s['topic']}: {s['summary']}")
        return "\n".join(lines)
