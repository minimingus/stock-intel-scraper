# OpenClaw AI Trader — Design Document

**Date:** 2026-02-28
**Status:** Approved

## Goal

Set up OpenClaw as an AI-driven Polymarket trading agent that autonomously analyzes prediction markets, decides where to bet, executes orders, and reports results via Telegram.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  OpenClaw Core                  │
│  (orchestrates skills, manages agent loop)      │
└──────────┬──────────────┬───────────────────────┘
           │              │
    ┌──────▼──────┐  ┌────▼──────────────────┐
    │   Polyclaw  │  │  Custom AI Reasoning   │
    │   Skill     │  │  Skill (Claude API)    │
    │  (Chainstack│  │                        │
    │   community)│  │  - Fetch open markets  │
    │             │  │  - Analyze with Claude │
    │  - Place    │  │  - Decide: bet or skip │
    │    orders   │  │  - Size the position   │
    │  - Get CLOB │  └────────────┬───────────┘
    │    data     │               │
    └──────┬──────┘               │
           └──────────┬───────────┘
                      │
               ┌──────▼──────┐
               │  Telegram   │
               │  Connector  │
               │  (built-in) │
               │             │
               │  - Trade    │
               │    alerts   │
               │  - Daily    │
               │    summaries│
               └─────────────┘
```

A scheduled loop (configurable interval, default 30 min) triggers the AI reasoning skill. It pulls current Polymarket markets, feeds them to Claude for analysis, and if the agent decides to bet, Polyclaw executes the order. Win/loss and reasoning are pushed to Telegram.

---

## Components

### 1. Wallet & Credentials (one-time setup)
- Generate a Polygon EOA wallet (private key stored in `.env`, never committed)
- Fund with USDC on Polygon (via bridge or direct purchase)
- Generate a Polymarket API key tied to that wallet
- Create a Telegram bot via BotFather, get bot token + chat ID

### 2. Polyclaw Skill (community, Chainstack)
- Installed from the `awesome-openclaw-skills` community repo
- Provides: fetch open markets, get current odds, place YES/NO orders, check positions
- Communicates with Polymarket's CLOB API using API key + wallet

### 3. AI Reasoning Skill (`skills/ai_trader.py`) — custom
- Runs on schedule (default: every 30 min, configurable)
- Per cycle:
  1. Call Polyclaw to get open markets with current odds
  2. Optionally fetch recent news headlines for context
  3. Send markets + context to Claude: *"Which markets are worth betting on, why, and how much?"*
  4. Parse Claude's structured response into decisions
  5. For each approved bet: call Polyclaw to execute, notify Telegram

### 4. Safety Rails (built into reasoning skill)
- `MAX_BET_USDC` — hard cap per single bet
- `MAX_DAILY_LOSS_USDC` — agent stops if daily loss exceeds limit
- `DRY_RUN=true` — logs decisions without placing real orders (for testing)

### Data Flow Per Cycle
```
Schedule trigger
  → fetch markets (Polyclaw)
  → fetch news (optional)
  → Claude analysis
  → parse decisions
  → [if DRY_RUN=false] place orders (Polyclaw)
  → send Telegram summary
```

---

## Project Structure

```
trader/
├── .env                        # secrets: wallet key, API keys, bot token
├── .env.example                # template (safe to commit)
├── config.yaml                 # trading params: interval, limits, markets filter
├── main.py                     # entry point — starts OpenClaw with skills loaded
├── skills/
│   └── ai_trader.py            # custom Claude-powered reasoning skill
├── docs/
│   └── plans/                  # design + implementation docs
├── requirements.txt            # dependencies
└── README.md                   # wallet setup instructions, how to run
```

## Configuration (`config.yaml`)

```yaml
trading:
  dry_run: true              # flip to false when ready for real money
  interval_minutes: 30       # how often the agent runs
  max_bet_usdc: 5.0          # cap per single bet
  max_daily_loss_usdc: 50.0  # daily stop-loss
  min_confidence: 0.70       # Claude must be ≥70% confident to bet

markets:
  categories: []             # empty = all; or e.g. ["politics", "crypto"]
  min_volume_usdc: 1000      # ignore low-liquidity markets
```

## Secrets (`.env`, never committed)

```
POLYGON_PRIVATE_KEY=0x...
POLYMARKET_API_KEY=...
POLYMARKET_API_SECRET=...
ANTHROPIC_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

---

## Key Dependencies

| Package | Purpose |
|---|---|
| `openclaw` | Agent framework |
| `py-clob-client` | Polymarket CLOB API |
| `anthropic` | Claude API for reasoning |
| `python-telegram-bot` | Telegram notifications |
| `pyyaml` | Config loading |
| `python-dotenv` | `.env` loading |

---

## Out of Scope (for now)
- News API integration (add later if needed)
- Web dashboard / UI
- Multiple exchange support
- Backtesting framework
