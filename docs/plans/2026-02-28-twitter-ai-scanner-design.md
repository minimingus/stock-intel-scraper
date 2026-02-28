# Twitter AI Scanner — Design Document

**Date:** 2026-02-28
**Status:** Approved

---

## Goal

Build a scheduled Twitter/X scanner that tracks top AI contributors and synthesizes their activity into a Telegram digest every 4 hours, plus a daily brief at 9am UTC. Signals from the scanner also feed into the Polymarket trading agent's Claude reasoning prompt as market context.

---

## Architecture

```
TwitterScanner (APScheduler — every 4h)
  │
  ├─ TweetFetcher (twikit — unofficial cookie auth)
  │    - Loads account list from config.yaml
  │    - Fetches tweets posted since last scan window
  │    - Deduplicates via seen-tweet ID store (data/seen_tweets.json)
  │
  ├─ RelevanceFilter
  │    - Keyword boost pass: model names, tool names, release terms
  │    - Drops pure retweets unless they add commentary
  │    - Minimum engagement threshold (configurable, default: 5 likes)
  │
  ├─ Synthesizer (Claude API)
  │    - Groups filtered tweets by topic bucket:
  │        new models/releases | new tools/products |
  │        research breakthroughs | devtools | community
  │    - Writes one narrative paragraph per non-empty bucket
  │    - Returns structured JSON: {topic, summary, tweets: [{author, text, url}]}
  │
  ├─ SignalStore  →  data/ai_signals.json
  │    - Persists structured signals (topic, summary, sources, timestamp)
  │    - Trading agent reads last 6h of signals as context on each reasoning cycle
  │
  └─ TelegramNotifier
       - Sends formatted digest every 4h
       - At 9am UTC: sends richer "Daily Brief" consolidating past 24h signals
```

---

## Accounts Tracked

Configured in `config.yaml` under `twitter.accounts`. Default curated list:

### Orgs / official
`AnthropicAI`, `OpenAI`, `GoogleDeepMind`, `cursor_ai`, `github`, `vercel`,
`huggingface`, `LangChainAI`, `llama_index`, `mistralai`

### Key people
`dario_amodei`, `sama`, `ylecun`, `karpathy`, `ilyasut`, `gdb`,
`simonw`, `swyx`, `amasad`, `levelsio`, `dhh`, `GregBrockman`

### DevTools influencers
`wesbos`, `kentcdodds`, `t3dotgg`, `_developit`, `mjackson`

All accounts are editable in `config.yaml` without touching code.

---

## Filtering Rules

- Drop pure retweets with no added commentary
- Minimum engagement: 5 likes (configurable via `twitter.min_engagement`)
- Keyword boost list (matches bump relevance score):
  `release`, `launch`, `new`, `model`, `API`, `open source`, `benchmark`,
  `GPT`, `Claude`, `Gemini`, `Llama`, `agent`, `coding`, `cursor`, `copilot`

---

## Synthesizer Prompt Strategy

Each 4h cycle Claude receives the filtered tweet batch and is instructed to:
1. Group tweets into topic buckets
2. Write one narrative paragraph per non-empty bucket — concise, factual, no hype
3. Return structured JSON: `{topic, summary, tweets: [{author, text, url}]}`

---

## Telegram Output Format

### Every-4h digest
```
🤖 AI Pulse — [HH:MM – HH:MM UTC]

📦 New Releases
[narrative paragraph]

🔬 Research
[narrative paragraph]

🛠 Dev Tools
[narrative paragraph]

Sources: @author1, @author2 ...
```

### Daily Brief (9am UTC)
Claude re-synthesizes all signals from past 24h into a "what mattered today" narrative, posted as a separate Telegram message with a `📰 Daily AI Brief` header.

---

## Signal Store (`data/ai_signals.json`)

Each signal record:
```json
{
  "id": "uuid",
  "timestamp": "ISO8601",
  "topic": "new_release | research | devtools | tools | community",
  "summary": "narrative text",
  "sources": ["https://x.com/..."],
  "relevance_score": 0.85
}
```

The file is appended on each scan and pruned to the last 7 days. Gitignored.

---

## Trader Integration

`src/polymarket.py` is extended to read `data/ai_signals.json` before each Claude reasoning call. Signals from the last 6h are appended to the prompt as:

```
Recent AI news context (last 6h):
- [topic]: [summary]
- ...
```

This allows Claude to factor in, e.g., a new model release when evaluating AI-related prediction markets.

---

## Project Structure

```
trader/
├── src/
│   ├── twitter/
│   │   ├── __init__.py
│   │   ├── fetcher.py        # twikit-based account tweet fetching
│   │   ├── filter.py         # relevance filtering
│   │   ├── synthesizer.py    # Claude synthesis → structured JSON
│   │   ├── signal_store.py   # read/write data/ai_signals.json
│   │   └── notifier.py       # Telegram digest sender
│   └── scanner.py            # APScheduler entry point
├── data/
│   ├── ai_signals.json       # live signal store (gitignored)
│   └── seen_tweets.json      # dedup store (gitignored)
└── scripts/
    └── run_scanner.sh         # launch scanner as background process
```

---

## Configuration (`config.yaml` additions)

```yaml
twitter:
  scan_interval_hours: 4
  daily_brief_hour_utc: 9
  min_engagement: 5
  accounts:
    - AnthropicAI
    - OpenAI
    - GoogleDeepMind
    - cursor_ai
    - github
    - vercel
    - huggingface
    - LangChainAI
    - llama_index
    - mistralai
    - dario_amodei
    - sama
    - ylecun
    - karpathy
    - ilyasut
    - gdb
    - simonw
    - swyx
    - amasad
    - levelsio
    - dhh
    - GregBrockman
    - wesbos
    - kentcdodds
    - t3dotgg
    - _developit
    - mjackson
  keywords_boost:
    - release
    - launch
    - new model
    - API
    - open source
    - benchmark
    - GPT
    - Claude
    - Gemini
    - Llama
    - agent
    - coding
    - cursor
    - copilot

signal_feed:
  lookback_hours: 6    # how many hours of signals the trader reads
```

---

## New Secrets (`.env`)

```
TWITTER_USERNAME=...
TWITTER_PASSWORD=...
TWITTER_EMAIL=...       # required by twikit for 2FA flows
```

---

## Key Dependencies

| Package | Purpose |
|---|---|
| `twikit` | Unofficial Twitter scraping via cookie auth |
| `anthropic` | Claude synthesis (already present) |
| `apscheduler` | Scheduling scans + daily brief |
| `python-telegram-bot` | Telegram delivery (already present) |

---

## Out of Scope (for now)

- Twitter Lists support (use account list instead)
- Sentiment scoring beyond relevance filtering
- Web dashboard for signals
- Historical backfill of tweets older than the first scan
