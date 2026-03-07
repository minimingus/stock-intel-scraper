import logging
import math
from collections import defaultdict
from datetime import datetime, timezone

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)

_DECAY_HALFLIFE_DAYS = 90.0
_DECAY_LAMBDA = math.log(2) / _DECAY_HALFLIFE_DAYS


def _decay_weight(days_ago: float) -> float:
    """Exponential decay weight. w=1.0 for today, w=0.5 at 90 days, w=0.125 at 270 days."""
    return math.exp(-_DECAY_LAMBDA * days_ago)


def _frequency_multiplier(calls_per_week: float) -> float:
    """Penalise high-frequency callers. Returns a value in (0, 1] that decreases as volume increases."""
    return 1.0 / math.log(calls_per_week + math.e)


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


class ExpertScorer:
    def __init__(self, store: TwitterIntelStore, lookback_hours: int = 168):
        self.store = store
        self.lookback_hours = lookback_hours

    def score(self) -> list[dict]:
        """
        Score experts using time-decayed expectancy (90-day half-life).
        Requires >= 3 closed trades per expert.
        Returns list sorted by adjusted_expectancy desc.
        """
        now = datetime.now(timezone.utc)
        signal_counts = self.store.get_expert_signal_counts(lookback_days=30)
        raw_trades = self.store.get_expert_trades_for_scoring()

        by_expert: dict = defaultdict(list)
        for t in raw_trades:
            by_expert[t["expert_handle"]].append(t)

        result = []
        for handle, trades in by_expert.items():
            if len(trades) < 3:
                continue

            total_w = 0.0
            win_w = 0.0
            win_pnl_w = 0.0
            loss_pnl_w = 0.0
            gross_win = 0.0
            gross_loss = 0.0
            max_gain_w = 0.0
            max_dd_w = 0.0
            days_held_w = 0.0

            for t in trades:
                try:
                    closed = datetime.fromisoformat(t["closed_at"])
                    if closed.tzinfo is None:
                        closed = closed.replace(tzinfo=timezone.utc)
                    days_ago = (now - closed).total_seconds() / 86400
                except Exception:
                    days_ago = 0.0
                w = _decay_weight(days_ago)
                pnl = t["pnl_pct"] or 0.0
                total_w += w
                if t["outcome"] == "win":
                    win_w += w
                    win_pnl_w += pnl * w
                    gross_win += pnl * w
                else:
                    loss_pnl_w += pnl * w
                    gross_loss += abs(pnl) * w
                if t.get("max_gain_pct") is not None:
                    max_gain_w += (t["max_gain_pct"] or 0.0) * w
                if t.get("max_drawdown_pct") is not None:
                    max_dd_w += (t["max_drawdown_pct"] or 0.0) * w
                if t.get("days_held") is not None:
                    days_held_w += (t["days_held"] or 0.0) * w

            win_rate = win_w / total_w if total_w else 0.0
            avg_win = win_pnl_w / win_w if win_w else 0.0
            avg_loss = loss_pnl_w / (total_w - win_w) if (total_w - win_w) else 0.0
            expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

            total = len(trades)
            wins = sum(1 for t in trades if t["outcome"] == "win")
            losses = total - wins
            wilson_conf = _wilson_lower(wins, total)
            adjusted_expectancy = expectancy * wilson_conf
            calls_per_week = signal_counts.get(handle, 0) / 4.0  # 30 days ≈ 4 weeks
            freq_mult = _frequency_multiplier(calls_per_week)
            adjusted_expectancy = adjusted_expectancy * freq_mult
            profit_factor = gross_win / (gross_loss or 0.0001)

            result.append({
                "handle": handle,
                "win_rate": win_rate,
                "wins": wins,
                "losses": losses,
                "total": total,
                "avg_pnl_pct": sum(t["pnl_pct"] or 0 for t in trades) / total,
                "avg_win_pct": avg_win,
                "avg_loss_pct": avg_loss,
                "expectancy": expectancy,
                "wilson_conf": wilson_conf,
                "adjusted_expectancy": adjusted_expectancy,
                "calls_per_week": calls_per_week,
                "freq_multiplier": freq_mult,
                "profit_factor": profit_factor,
                "avg_max_gain": max_gain_w / total_w if total_w else 0.0,
                "avg_max_drawdown": max_dd_w / total_w if total_w else 0.0,
                "avg_days_held": days_held_w / total_w if total_w else 0.0,
            })

        return sorted(result, key=lambda x: x["adjusted_expectancy"], reverse=True)
