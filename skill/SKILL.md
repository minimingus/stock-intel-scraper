---
name: ai-polymarket-trader
description: AI-driven Polymarket prediction market trading agent — runs cycles, checks portfolio
metadata:
  openclaw:
    requires:
      bins: ["python3"]
      env:
        - POLYGON_PRIVATE_KEY
        - POLYMARKET_FUNDER_ADDRESS
        - ANTHROPIC_API_KEY
        - TELEGRAM_BOT_TOKEN
        - TELEGRAM_CHAT_ID
---

# AI Polymarket Trader

Use this skill when the user asks to:
- "Run a trading cycle" or "analyze markets now" or "check for bets"
- "Show my portfolio" or "what positions do I have"
- "How much have I bet today"

## Instructions

When the user asks to run a cycle or analyze markets:
1. Run: `python3 /Users/tomerab/dev/trader/skill/scripts/trigger_cycle.py`
2. Report the printed output to the user

When the user asks about portfolio or positions:
1. Run: `python3 /Users/tomerab/dev/trader/skill/scripts/query_portfolio.py`
2. Report the printed output to the user

When the user asks to enable/disable dry run:
1. Tell them to edit `dry_run:` in `/Users/tomerab/dev/trader/config.yaml`
2. Confirm: "Set dry_run to true to simulate, false to trade real money"
