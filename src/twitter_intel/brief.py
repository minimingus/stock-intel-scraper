import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path

import requests
import yfinance as yf

from .store import TwitterIntelStore
from . import market_context as mctx
from . import finviz_scraper as fvz

logger = logging.getLogger(__name__)

_MIN_SIGNALS = 5
_LOOKBACK_STEPS = [24, 48, 72, 120]
_PROVEN_MIN_TRADES = 8
_PROVEN_MIN_EXPECTANCY = 0.0
_ACCOUNT_SIZE = float(os.environ.get("ACCOUNT_SIZE", "10000"))
_RISK_PER_TRADE_PCT = 0.01


def _fetch_price(ticker: str) -> float | None:
    try:
        hist = yf.Ticker(ticker).history(period="1d", interval="5m")
        return float(hist["Close"].iloc[-1]) if not hist.empty else None
    except Exception:
        return None


def _dedup_ta_notes(raw: str | None) -> str:
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


def _rr_and_size(entry: float, target: float, stop: float) -> str:
    risk = entry - stop
    reward = target - entry
    if risk <= 0:
        return ""
    rr = reward / risk
    shares = int((_ACCOUNT_SIZE * _RISK_PER_TRADE_PCT) / risk)
    return f"R:R 1:{rr:.1f} · Size ~{shares} shares (5% stop, 1% risk)"


def _build_brief(signals: list, expert_scores: list, store: TwitterIntelStore) -> str:
    today = date.today().strftime("%b %d, %Y")
    lines = [f"📊 <b>Daily Trading Brief — {today}</b>\n"]

    # Market sentiment header
    sentiment = mctx.market_sentiment()
    if sentiment["warning"]:
        lines.append(f"⚠️ <b>{sentiment['warning']}</b>")
        if sentiment["vix"] is not None:
            lines.append(f"   VIX: {sentiment['vix']:.1f} — elevated fear, reduce position sizes\n")
        else:
            lines.append("")
    elif sentiment["regime"] == "bull":
        spy_str = f"SPY {sentiment['spy_change']*100:+.1f}%" if sentiment["spy_change"] is not None else ""
        qqq_str = f"QQQ {sentiment['qqq_change']*100:+.1f}%" if sentiment["qqq_change"] is not None else ""
        index_str = " · ".join(filter(None, [spy_str, qqq_str]))
        lines.append(f"🟩 Market tailwind: {index_str}\n")

    # Sentiment score modifier for confidence
    sent_score = sentiment["sentiment_score"]  # [-1, +1]

    # Build expert lookup
    expert_map = {e["handle"]: e for e in expert_scores}

    def _confidence(s: dict) -> tuple[str, float]:
        handles = [h.strip() for h in (s.get("experts") or "").split(",") if h.strip()]
        score = 0.0
        proven_count = 0
        for h in handles:
            e = expert_map.get(h)
            if e and e["total"] >= _PROVEN_MIN_TRADES and e.get("adjusted_expectancy", e["expectancy"]) > _PROVEN_MIN_EXPECTANCY:
                score += max(e["expectancy"], 0.01)
                proven_count += 1
            else:
                score += 0.001
        # Apply market sentiment modifier: bear reduces score, bull boosts
        score = score * (1.0 + sent_score * 0.3)
        tier = "HIGH" if proven_count >= 1 else ("MEDIUM" if handles else "LOW")
        # In a bear market, MEDIUM signals are demoted if no proven expert
        if tier == "MEDIUM" and sentiment["regime"] == "bear":
            tier = "LOW"
        return tier, score

    # Sort signals: HIGH first, then MEDIUM; drop LOW
    tiered = []
    for s in signals:
        tier, score = _confidence(s)
        if tier != "LOW":
            tiered.append((tier, score, s))
    tiered.sort(key=lambda x: (0 if x[0] == "HIGH" else 1, -x[1]))

    if tiered:
        lines.append("🏦 <b>Stocks to Watch</b>")
        for tier, score, s in tiered:
            ticker = s["ticker"]
            day = s.get("day_count") or 0
            swing = s.get("swing_count") or 0
            trade_type = "day" if day >= swing else "swing"
            trade_label = "📅 Day" if trade_type == "day" else "📆 Swing"
            tier_icon = "🔥" if tier == "HIGH" else "🔵"
            n_experts = s["expert_count"]

            ctx = mctx.ticker_context(ticker)
            entry = _fetch_price(ticker)
            avg_target = s.get("avg_target")
            ta_notes = _dedup_ta_notes(s.get("all_ta_notes"))

            entry_str = f"${entry:.2f}" if entry else "N/A"
            target_str = ""
            rr_str = ""
            if entry and avg_target and avg_target > entry:
                gain_pct = (avg_target - entry) / entry * 100
                target_str = f"→ ${avg_target:.2f} (+{gain_pct:.1f}%)"
                stop_price = entry * 0.95
                rr_str = _rr_and_size(entry, avg_target, stop_price)

            # Intraday context
            ctx_parts = []
            if ctx["change_pct"] is not None:
                ctx_parts.append(f"{ctx['change_pct']*100:+.1f}% today")
            if ctx["volume_ratio"] is not None:
                ctx_parts.append(f"Vol {ctx['volume_ratio']:.1f}× avg")
            ctx_str = " · ".join(ctx_parts)

            # Ticker paper history
            hist = store.get_ticker_paper_history(ticker)
            hist_str = ""
            if hist and hist["total"]:
                avg_pnl = (hist['avg_pnl_pct'] or 0) * 100
                hist_str = (
                    f"📊 {hist['total']} calls · {hist['wins']}W/{hist['losses']}L · "
                    f"avg {avg_pnl:+.1f}%"
                )

            age_str = _signal_age_label(s.get("latest_signal_time"), trade_type)

            # Earnings proximity
            earn_days = mctx.earnings_proximity(ticker)
            earn_str = ""
            if earn_days is not None and earn_days <= 7:
                earn_str = f"⚠️ Earnings in {earn_days}d — elevated risk"
                if earn_days <= 3 and tier == "HIGH":
                    tier = "MEDIUM"
                    tier_icon = "🔵"

            # Unusual options flow
            flow = mctx.options_flow(ticker)
            flow_str = ""
            if flow:
                flow_str = f"🔮 Options: {flow['call_volume']:,} calls · Vol/OI {flow['max_vol_oi']}×"

            # Already-moved chasing warning
            chase_str = ""
            if ctx["change_pct"] is not None and ctx["change_pct"] > 0.03:
                chase_str = f"📈 Already +{ctx['change_pct']*100:.1f}% today — wait for pullback"

            # Short interest
            short_pct = fvz.short_interest(ticker)
            short_str = ""
            if short_pct is not None and short_pct > 0.10:
                squeeze = " — squeeze potential" if short_pct > 0.20 else ""
                short_str = f"Short: {short_pct*100:.1f}% float{squeeze}"

            expert_handles = [f"@{h.strip()}" for h in (s.get("experts") or "").split(",") if h.strip()]
            experts_str = " ".join(expert_handles)
            lines.append(
                f"  {tier_icon} <b>${ticker}</b> — {trade_label} · Score {score:.3f}"
            )
            lines.append(f"     {experts_str}")
            price_line = f"     Entry: {entry_str}"
            if target_str:
                price_line += f"  Target: {target_str}"
            lines.append(price_line)
            if rr_str:
                lines.append(f"     {rr_str}")
            if ctx_str:
                lines.append(f"     {ctx_str}")
            if chase_str:
                lines.append(f"     {chase_str}")
            if earn_str:
                lines.append(f"     {earn_str}")
            if flow_str:
                lines.append(f"     {flow_str}")
            if short_str:
                lines.append(f"     {short_str}")
            if hist_str:
                lines.append(f"     {hist_str}")
            if ta_notes:
                lines.append(f"     <i>{ta_notes}</i>")
            if age_str:
                lines.append(f"     🕐 {age_str}")
            lines.append("")
    else:
        if sentiment["regime"] == "bear":
            lines.append("<i>No HIGH-confidence signals — bear market filter active.</i>\n")
        else:
            lines.append("<i>No validated signals found.</i>\n")

    # Expert leaderboard
    if expert_scores:
        lines.append("🏆 <b>Expert Performance</b> <i>(OHLC-verified paper trades)</i>")
        for e in expert_scores[:5]:
            win_rate = int(e["win_rate"] * 100)
            exp = e["expectancy"] * 100
            pf = e["profit_factor"]
            days = e["avg_days_held"]
            bar = "▓" * (win_rate // 10) + "░" * (10 - win_rate // 10)
            exp_sign = "+" if exp >= 0 else ""
            wilson = int((e.get("wilson_conf") or 0) * 100)
            lines.append(
                f"  @{e['handle']} {bar} {win_rate}% · "
                f"E={exp_sign}{exp:.1f}% · Conf={wilson}% · PF={pf:.2f} · "
                f"{e['wins']}W/{e['losses']}L · {days:.1f}d avg"
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

        text = _build_brief(signals, expert_scores, self.store)
        mctx.clear_cache()
        fvz.clear_cache()

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
