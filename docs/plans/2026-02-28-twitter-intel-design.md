# Twitter Intel — Design Document

**Date:** 2026-02-28
**Status:** Approved

## Goal

Add a Twitter/X intelligence layer to OpenClaw that monitors top daily trading experts, extracts stock/crypto/Polymarket signals from their tweets, and delivers a daily brief via Telegram every morning at 8am.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Twitter Intel Module                   │
│              (src/twitter_intel/)                       │
├──────────────┬──────────────┬───────────────────────────┤
│  Scraper     │  Store       │  SignalExtractor           │
│  (Playwright)│  (SQLite)    │  (Claude API)              │
│              │              │                            │
│  Every 4h:   │  experts     │  Reads new tweets         │
│  - Load expert│  table       │  Extracts tickers,        │
│    handles   │  tweets      │  crypto, polymarket refs  │
│  - Visit each │  table       │  Scores by expert count   │
│    user page │  signals     │  + sentiment              │
│  - Grab latest│  table       │                           │
│    tweets    │              │                            │
└──────┬───────┴──────┬───────┴──────────┬────────────────┘
       │              │                  │
       └──────────────▼──────────────────▼
              ┌────────────────────────┐
              │   BriefGenerator       │
              │   (daily at 8am)       │
              │                        │
              │  Claude synthesizes    │
              │  → Top 3 stocks        │
              │  → Top 3 crypto        │
              │  → Top 3 polymarket    │
              │  → sends via Telegram  │
              └────────────────────────┘

  Auto-expand (1x/day): looks at who seed accounts
  retweet/reply to → discovers new expert handles
```

The module runs as a standalone APScheduler process, decoupled from the Polymarket trading loop. It shares only Telegram credentials and config.

---

## Data Model

SQLite database at `data/twitter_intel.db`.

```sql
-- Who we monitor
experts (
  handle       TEXT PRIMARY KEY,
  source       TEXT,      -- 'seed' | 'discovered'
  added_date   TEXT,
  active       INTEGER    -- 1/0
)

-- Raw tweet storage (pruned after 7 days)
tweets (
  tweet_id     TEXT PRIMARY KEY,
  handle       TEXT,
  text         TEXT,
  likes        INTEGER,
  retweets     INTEGER,
  scraped_at   TEXT
)

-- Extracted signals (one row per ticker mention per tweet)
signals (
  id           INTEGER PRIMARY KEY,
  tweet_id     TEXT,
  ticker       TEXT,      -- e.g. NVDA, BTC, or polymarket question slug
  asset_type   TEXT,      -- 'stock' | 'crypto' | 'polymarket'
  sentiment    TEXT,      -- 'bullish' | 'bearish' | 'neutral'
  extracted_at TEXT
)
```

Brief ranking: signals from last 24h grouped by ticker, sorted by `count(distinct handle)` descending. Tickers must be mentioned by >= `min_expert_mentions` different experts to appear.

---

## Configuration

New section in `config.yaml`:

```yaml
twitter_intel:
  brief_time: "08:00"
  scrape_interval_hours: 4
  lookback_hours: 24
  min_expert_mentions: 2

  auto_expand:
    enabled: true
    max_accounts: 100
    min_interactions: 3

  seed_accounts:
    - RaoulGMI
    - CryptoCapo_
    - tier10k
    - MacroAlf
    - TraderSZ
    - zerohedge
    - unusual_whales
    - stockmoe
    - CryptoBull2020
    - inversebrah
```

---

## Scheduling (APScheduler, in-process)

| Job | Interval | Description |
|-----|----------|-------------|
| scrape | Every 4h | Playwright scrapes all active expert timelines |
| extract | Every 4h (offset +5min) | Claude extracts signals from new tweets |
| brief | Daily 08:00 | Claude synthesizes 24h signals → Telegram |
| expand | Daily 02:00 | Auto-discover new experts, prune old tweets |

---

## File Structure

```
trader/
├── config.yaml                      # updated with twitter_intel section
├── data/
│   └── twitter_intel.db             # SQLite (gitignored)
├── src/
│   ├── twitter_intel/
│   │   ├── __init__.py
│   │   ├── scraper.py               # Playwright scraping logic
│   │   ├── store.py                 # SQLite read/write
│   │   ├── extractor.py             # Claude signal extraction
│   │   ├── brief.py                 # Brief generation + Telegram send
│   │   ├── discovery.py             # Auto-expand expert list
│   │   └── scheduler.py             # APScheduler setup + entry point
│   └── polymarket.py                # existing, unchanged
├── scripts/
│   └── run_intel.py                 # manual trigger
└── tests/
    └── test_twitter_intel/
        ├── test_store.py
        ├── test_extractor.py
        └── test_brief.py
```

**New dependencies:**
- `playwright>=1.45.0`
- `apscheduler>=3.10.0`

**No new env vars** — uses existing `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

---

## Brief Format (Telegram)

```
📊 *Daily Trading Brief — Feb 28*

🏦 *Stocks to Watch*
1. $NVDA — mentioned by 7 experts · Bullish · "Jensen confirming AI cycle continues"
2. $TSLA — mentioned by 4 experts · Mixed · "options flow unusual, watch $280"
3. $PLTR — mentioned by 3 experts · Bullish · "breakout above $85 imminent"

🪙 *Crypto Signals*
1. BTC — mentioned by 9 experts · Bullish · "accumulation at $90k, weekly close key"
2. SOL — mentioned by 5 experts · Bullish · "ETF narrative building"
3. ETH — mentioned by 3 experts · Neutral · "underperforming, range-bound"

🎯 *Polymarket Attention*
1. "Will BTC hit $100k before April?" — 4 experts discussing · Yes trending up
2. "US recession by Q3 2026?" — 3 experts · Contrarian bets appearing

⚡ _8 new experts discovered this week_
📡 _Monitoring 47 accounts · 1,203 tweets analyzed_
```

---

## Error Handling

- Playwright failures (login wall, rate limit, element not found): log and skip that handle, continue with next
- Claude API failures: retry once, then skip extraction for this batch (raw tweets still saved)
- Telegram failure: log error, write brief to `logs/brief-YYYY-MM-DD.txt` as fallback
- X login wall: scraper attempts to load public profile; if redirected to login, marks handle as `needs_auth` and skips
