import os
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OpenOrderParams, OrderType
from py_clob_client.order_builder.constants import BUY


class PolymarketClient:
    def __init__(self):
        self._clob = ClobClient(
            "https://clob.polymarket.com",
            key=os.environ["POLYGON_PRIVATE_KEY"],
            chain_id=137,
            signature_type=2,
            funder=os.environ["POLYMARKET_FUNDER_ADDRESS"],
        )
        self._clob.set_api_creds(self._clob.create_or_derive_api_creds())

    def get_open_markets(self, min_volume: float = 1000) -> list[dict]:
        markets = []
        cursor = None
        while True:
            resp = (
                self._clob.get_markets(next_cursor=cursor)
                if cursor
                else self._clob.get_markets()
            )
            for m in resp.get("data", []):
                if m.get("active") and float(m.get("volume", 0)) >= min_volume:
                    markets.append({
                        "condition_id": m["condition_id"],
                        "question": m["question"],
                        "outcomes": m.get("outcomes", []),
                        "outcome_prices": m.get("outcome_prices", []),
                        "volume": float(m.get("volume", 0)),
                        "token_ids": [t["token_id"] for t in m.get("tokens", [])],
                    })
            cursor = resp.get("next_cursor")
            if not cursor or cursor == "LTE=":
                break
        return markets

    def place_market_order(
        self, token_id: str, amount_usdc: float, dry_run: bool = True
    ) -> dict:
        if dry_run:
            return {"dry_run": True, "token_id": token_id, "amount_usdc": amount_usdc}
        mo = MarketOrderArgs(token_id=token_id, amount=amount_usdc, side=BUY)
        signed = self._clob.create_market_order(mo)
        return self._clob.post_order(signed, OrderType.FOK)

    def get_positions(self) -> list[dict]:
        raw = self._clob.get_orders(OpenOrderParams())
        return [dict(o) for o in (raw or [])]
