#!/usr/bin/env python3
import os, sys
sys.path.insert(0, "/Users/tomerab/dev/trader")
from dotenv import load_dotenv
load_dotenv("/Users/tomerab/dev/trader/.env")
import yaml
from src.polymarket import PolymarketClient
from src.analysis import MarketAnalyzer
from src.notifier import TelegramNotifier
from src.cycle import TradingCycle

with open("/Users/tomerab/dev/trader/config.yaml") as f:
    cfg = yaml.safe_load(f)

t = cfg["trading"]
result = TradingCycle(
    polymarket=PolymarketClient(),
    analyzer=MarketAnalyzer(api_key=os.environ["ANTHROPIC_API_KEY"]),
    notifier=TelegramNotifier(
        bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        chat_id=os.environ["TELEGRAM_CHAT_ID"],
    ),
    dry_run=t["dry_run"],
    max_bet_usdc=t["max_bet_usdc"],
    min_confidence=t["min_confidence"],
).run()

status = "DRY RUN" if t["dry_run"] else "LIVE"
print(f"[{status}] Cycle complete: {result['bets_placed']} bets, ${result['total_usdc']:.2f} total")
