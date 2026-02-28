import os
import pytest
from unittest.mock import patch, MagicMock

# Provide dummy env vars so the module can be imported in tests
os.environ.setdefault("POLYGON_PRIVATE_KEY", "0x" + "a" * 64)
os.environ.setdefault("POLYMARKET_FUNDER_ADDRESS", "0x" + "0" * 40)


def _make_client():
    with patch("src.polymarket.ClobClient") as MockClient:
        instance = MockClient.return_value
        instance.create_or_derive_api_creds.return_value = {}
        from src.polymarket import PolymarketClient
        return PolymarketClient(), instance


def test_get_markets_returns_active_markets_above_min_volume():
    client, mock_clob = _make_client()
    mock_clob.get_markets.return_value = {
        "data": [
            {
                "condition_id": "abc123",
                "question": "Will BTC reach $100k by end of 2026?",
                "active": True,
                "volume": "5000.0",
                "outcomes": ["Yes", "No"],
                "outcome_prices": ["0.65", "0.35"],
                "tokens": [{"token_id": "tok_yes"}, {"token_id": "tok_no"}],
            }
        ],
        "next_cursor": "LTE=",
    }

    markets = client.get_open_markets(min_volume=1000)

    assert len(markets) == 1
    assert markets[0]["question"] == "Will BTC reach $100k by end of 2026?"
    assert markets[0]["token_ids"] == ["tok_yes", "tok_no"]
    assert markets[0]["volume"] == 5000.0


def test_get_markets_filters_low_volume():
    client, mock_clob = _make_client()
    mock_clob.get_markets.return_value = {
        "data": [
            {
                "condition_id": "abc123",
                "question": "Tiny market",
                "active": True,
                "volume": "50.0",
                "outcomes": ["Yes", "No"],
                "outcome_prices": ["0.5", "0.5"],
                "tokens": [{"token_id": "tok_yes"}, {"token_id": "tok_no"}],
            }
        ],
        "next_cursor": "LTE=",
    }

    markets = client.get_open_markets(min_volume=1000)

    assert len(markets) == 0


def test_place_order_dry_run_returns_without_calling_post():
    client, mock_clob = _make_client()

    result = client.place_market_order("tok_yes", 5.0, dry_run=True)

    assert result["dry_run"] is True
    assert result["token_id"] == "tok_yes"
    assert result["amount_usdc"] == 5.0
    mock_clob.post_order.assert_not_called()


def test_place_order_executes_when_not_dry_run():
    client, mock_clob = _make_client()
    mock_clob.create_market_order.return_value = MagicMock()
    mock_clob.post_order.return_value = {"status": "matched", "order_id": "ord_1"}

    result = client.place_market_order("tok_yes", 5.0, dry_run=False)

    assert result["order_id"] == "ord_1"
    mock_clob.post_order.assert_called_once()


def test_get_positions_returns_list_of_dicts():
    client, mock_clob = _make_client()
    mock_clob.get_orders.return_value = [
        {"id": "ord_1", "token_id": "tok_yes", "status": "LIVE"},
    ]

    positions = client.get_positions()

    assert len(positions) == 1
    assert positions[0]["id"] == "ord_1"
    assert isinstance(positions[0], dict)
