from unittest.mock import MagicMock

MARKETS = [
    {
        "condition_id": "abc123",
        "question": "Will Fed cut rates in March 2026?",
        "outcomes": ["Yes", "No"],
        "outcome_prices": ["0.72", "0.28"],
        "volume": 50000.0,
        "token_ids": ["tok_yes", "tok_no"],
    }
]

DECISIONS = [
    {
        "condition_id": "abc123",
        "action": "BUY_YES",
        "token_id": "tok_yes",
        "confidence": 0.80,
        "amount_usdc": 4.0,
        "reasoning": "Fed signaled cuts",
    }
]


def _make_cycle(dry_run=True):
    from src.cycle import TradingCycle
    poly = MagicMock()
    analyzer = MagicMock()
    notifier = MagicMock()
    cycle = TradingCycle(
        poly, analyzer, notifier,
        dry_run=dry_run, max_bet_usdc=5.0, min_confidence=0.70
    )
    return cycle, poly, analyzer, notifier


def test_cycle_fetches_markets_and_runs_analysis():
    cycle, poly, analyzer, _ = _make_cycle()
    poly.get_open_markets.return_value = MARKETS
    analyzer.analyze.return_value = DECISIONS

    cycle.run()

    poly.get_open_markets.assert_called_once()
    analyzer.analyze.assert_called_once_with(
        MARKETS, max_bet_usdc=5.0, min_confidence=0.70
    )


def test_cycle_sends_alert_per_decision():
    cycle, poly, analyzer, notifier = _make_cycle(dry_run=True)
    poly.get_open_markets.return_value = MARKETS
    analyzer.analyze.return_value = DECISIONS

    cycle.run()

    notifier.send_trade_alert.assert_called_once()
    kw = notifier.send_trade_alert.call_args.kwargs
    assert kw["dry_run"] is True
    assert kw["action"] == "BUY_YES"
    assert kw["amount_usdc"] == 4.0


def test_cycle_dry_run_skips_place_order():
    cycle, poly, analyzer, _ = _make_cycle(dry_run=True)
    poly.get_open_markets.return_value = MARKETS
    analyzer.analyze.return_value = DECISIONS

    cycle.run()

    poly.place_market_order.assert_not_called()


def test_cycle_live_calls_place_order():
    cycle, poly, analyzer, _ = _make_cycle(dry_run=False)
    poly.get_open_markets.return_value = MARKETS
    analyzer.analyze.return_value = DECISIONS
    poly.place_market_order.return_value = {"order_id": "ord_1"}

    cycle.run()

    poly.place_market_order.assert_called_once_with(
        token_id="tok_yes", amount_usdc=4.0, dry_run=False
    )


def test_cycle_sends_summary_with_correct_counts():
    cycle, poly, analyzer, notifier = _make_cycle(dry_run=True)
    poly.get_open_markets.return_value = MARKETS
    analyzer.analyze.return_value = DECISIONS

    result = cycle.run()

    notifier.send_cycle_summary.assert_called_once()
    kw = notifier.send_cycle_summary.call_args.kwargs
    assert kw["bets_placed"] == 1
    assert kw["total_usdc"] == 4.0
    assert kw["markets_analyzed"] == 1
    assert result == {"bets_placed": 1, "total_usdc": 4.0}
