import json
import pytest
from unittest.mock import patch, MagicMock

SAMPLE_MARKETS = [
    {
        "condition_id": "abc123",
        "question": "Will the Fed cut rates in March 2026?",
        "outcomes": ["Yes", "No"],
        "outcome_prices": ["0.72", "0.28"],
        "volume": 50000.0,
        "token_ids": ["tok_yes", "tok_no"],
    }
]

SAMPLE_RESPONSE = json.dumps({
    "decisions": [
        {
            "condition_id": "abc123",
            "action": "BUY_YES",
            "token_id": "tok_yes",
            "confidence": 0.80,
            "amount_usdc": 4.0,
            "reasoning": "Fed has signaled cuts; market underprices at 0.72",
        }
    ]
})


def _make_analyzer(response_text):
    with patch("src.analysis.anthropic.Anthropic") as MockAnthropic:
        instance = MockAnthropic.return_value
        msg = MagicMock()
        msg.content = [MagicMock(text=response_text)]
        instance.messages.create.return_value = msg
        from src.analysis import MarketAnalyzer
        return MarketAnalyzer(api_key="fake"), instance


def test_analyze_returns_decisions():
    analyzer, _ = _make_analyzer(SAMPLE_RESPONSE)
    decisions = analyzer.analyze(SAMPLE_MARKETS, max_bet_usdc=5.0, min_confidence=0.70)

    assert len(decisions) == 1
    assert decisions[0]["action"] == "BUY_YES"
    assert decisions[0]["token_id"] == "tok_yes"


def test_analyze_filters_low_confidence():
    low_conf = json.dumps({"decisions": [
        {"condition_id": "abc123", "action": "BUY_YES", "token_id": "tok_yes",
         "confidence": 0.50, "amount_usdc": 4.0, "reasoning": "not sure"}
    ]})
    analyzer, _ = _make_analyzer(low_conf)
    decisions = analyzer.analyze(SAMPLE_MARKETS, max_bet_usdc=5.0, min_confidence=0.70)

    assert decisions == []


def test_analyze_clamps_amount_to_max_bet():
    over_bet = json.dumps({"decisions": [
        {"condition_id": "abc123", "action": "BUY_YES", "token_id": "tok_yes",
         "confidence": 0.90, "amount_usdc": 999.0, "reasoning": "very sure"}
    ]})
    analyzer, _ = _make_analyzer(over_bet)
    decisions = analyzer.analyze(SAMPLE_MARKETS, max_bet_usdc=5.0, min_confidence=0.70)

    assert decisions[0]["amount_usdc"] == 5.0


def test_analyze_returns_empty_list_on_invalid_json():
    analyzer, _ = _make_analyzer("this is not json at all")
    decisions = analyzer.analyze(SAMPLE_MARKETS, max_bet_usdc=5.0, min_confidence=0.70)

    assert decisions == []


def test_analyze_returns_empty_list_for_no_markets():
    analyzer, mock_client = _make_analyzer(SAMPLE_RESPONSE)
    decisions = analyzer.analyze([], max_bet_usdc=5.0, min_confidence=0.70)

    mock_client.messages.create.assert_not_called()
    assert decisions == []
