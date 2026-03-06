import logging

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)


class ExpertScorer:
    def __init__(self, store: TwitterIntelStore, lookback_hours: int = 168):
        self.store = store
        self.lookback_hours = lookback_hours

    def score(self) -> list[dict]:
        """
        Score experts based on closed paper trades.
        Returns list sorted by avg_pnl_pct desc (requires >= 3 closed trades).
        """
        rows = self.store.get_expert_paper_scores()
        result = []
        for r in rows:
            total = r["total"] or 0
            wins = r["wins"] or 0
            result.append({
                "handle": r["expert_handle"],
                "win_rate": wins / total if total else 0,
                "wins": wins,
                "total": total,
                "avg_pnl_pct": r["avg_pnl_pct"] or 0,
            })
        return result
