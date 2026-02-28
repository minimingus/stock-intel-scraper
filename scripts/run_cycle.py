#!/usr/bin/env python3
"""Entry point for the automated trading cycle. Called by launchd every 30 minutes."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

import yaml
from src.polymarket import PolymarketClient
from src.analysis import MarketAnalyzer
from src.notifier import TelegramNotifier
from src.cycle import TradingCycle


def main() -> None:
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")) as f:
        cfg = yaml.safe_load(f)

    trading = cfg["trading"]

    cycle = TradingCycle(
        polymarket=PolymarketClient(),
        analyzer=MarketAnalyzer(api_key=os.environ["ANTHROPIC_API_KEY"]),
        notifier=TelegramNotifier(
            bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
            chat_id=os.environ["TELEGRAM_CHAT_ID"],
        ),
        dry_run=trading["dry_run"],
        max_bet_usdc=trading["max_bet_usdc"],
        min_confidence=trading["min_confidence"],
    )
    result = cycle.run()
    print(f"Cycle complete: bets_placed={result['bets_placed']}, total_usdc=${result['total_usdc']:.2f}")


if __name__ == "__main__":
    main()
