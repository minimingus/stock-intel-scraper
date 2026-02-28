class TradingCycle:
    def __init__(self, polymarket, analyzer, notifier,
                 dry_run: bool = True, max_bet_usdc: float = 5.0,
                 min_confidence: float = 0.70):
        self._poly = polymarket
        self._analyzer = analyzer
        self._notifier = notifier
        self._dry_run = dry_run
        self._max_bet_usdc = max_bet_usdc
        self._min_confidence = min_confidence

    def run(self) -> dict:
        markets = self._poly.get_open_markets()
        decisions = self._analyzer.analyze(
            markets,
            max_bet_usdc=self._max_bet_usdc,
            min_confidence=self._min_confidence,
        )

        bets_placed = 0
        total_usdc = 0.0
        market_index = {m["condition_id"]: m["question"] for m in markets}

        for d in decisions:
            self._notifier.send_trade_alert(
                question=market_index.get(d["condition_id"], d["condition_id"]),
                action=d["action"],
                amount_usdc=d["amount_usdc"],
                confidence=d["confidence"],
                reasoning=d["reasoning"],
                dry_run=self._dry_run,
            )
            if not self._dry_run:
                self._poly.place_market_order(
                    token_id=d["token_id"],
                    amount_usdc=d["amount_usdc"],
                    dry_run=False,
                )
            bets_placed += 1
            total_usdc += d["amount_usdc"]

        self._notifier.send_cycle_summary(
            markets_analyzed=len(markets),
            bets_placed=bets_placed,
            total_usdc=total_usdc,
            dry_run=self._dry_run,
        )
        return {"bets_placed": bets_placed, "total_usdc": total_usdc}
