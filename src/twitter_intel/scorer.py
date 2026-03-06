import logging
import math

from .store import TwitterIntelStore


def _wilson_lower(wins: int, total: int, z: float = 1.96) -> float:
    """Lower bound of 95% Wilson confidence interval for win rate.

    Penalises small samples: 4/5 (80%) → 0.28, 40/50 (80%) → 0.67.
    """
    if total == 0:
        return 0.0
    p = wins / total
    return (
        p + z**2 / (2 * total)
        - z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total)
    ) / (1 + z**2 / total)

logger = logging.getLogger(__name__)


class ExpertScorer:
    def __init__(self, store: TwitterIntelStore, lookback_hours: int = 168):
        self.store = store
        self.lookback_hours = lookback_hours

    def score(self) -> list[dict]:
        """
        Score experts based on closed paper trades.
        Computes: win rate, expectancy, profit factor, avg days held.
        Requires >= 3 closed trades per expert.
        Returns list sorted by expectancy desc.
        """
        rows = self.store.get_expert_paper_scores()
        result = []
        for r in rows:
            total = r["total"] or 0
            wins = r["wins"] or 0
            losses = r["losses"] or 0
            win_rate = wins / total if total else 0

            avg_win = r["avg_win_pct"] or 0       # positive
            avg_loss = r["avg_loss_pct"] or 0     # negative

            # Expectancy: expected % return per trade
            # = (win_rate × avg_win) + (loss_rate × avg_loss)
            expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

            wilson_conf = _wilson_lower(wins, total)
            # Adjusted expectancy: penalises statistically weak track records
            adjusted_expectancy = expectancy * wilson_conf

            # Profit factor: gross wins / gross losses (> 1 = profitable)
            gross_win = r["gross_win"] or 0
            gross_loss = r["gross_loss"] or 0.0001  # avoid div/0
            profit_factor = gross_win / gross_loss

            result.append({
                "handle": r["expert_handle"],
                "win_rate": win_rate,
                "wins": wins,
                "losses": losses,
                "total": total,
                "avg_pnl_pct": r["avg_pnl_pct"] or 0,
                "avg_win_pct": avg_win,
                "avg_loss_pct": avg_loss,
                "expectancy": expectancy,
                "wilson_conf": wilson_conf,
                "adjusted_expectancy": adjusted_expectancy,
                "profit_factor": profit_factor,
                "avg_max_gain": r["avg_max_gain"] or 0,
                "avg_max_drawdown": r["avg_max_drawdown"] or 0,
                "avg_days_held": r["avg_days_held"] or 0,
            })

        return sorted(result, key=lambda x: x["adjusted_expectancy"], reverse=True)
