#!/usr/bin/env python3
import os, sys, json
sys.path.insert(0, "/Users/tomerab/dev/trader")
from dotenv import load_dotenv
load_dotenv("/Users/tomerab/dev/trader/.env")
from src.polymarket import PolymarketClient

positions = PolymarketClient().get_positions()
if positions:
    print(json.dumps(positions, indent=2))
else:
    print("No open positions.")
