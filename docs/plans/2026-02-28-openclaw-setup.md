# OpenClaw AI Trader — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Set up an AI-driven Polymarket trading agent using OpenClaw with Claude-powered market analysis and Telegram alerts, starting from an empty directory.

**Architecture:** A Python trading core (Polymarket client, Claude analyzer, Telegram notifier, cycle orchestrator) runs on a 30-minute launchd schedule. An OpenClaw skill wraps it for interactive queries and manual triggers via Telegram chat. `dry_run: true` is on by default — flip to false when ready for real money.

**Tech Stack:** Python 3.11+, OpenClaw (npm, Node 22+), py-clob-client==0.29.0, web3==6.14.0, anthropic>=0.40.0, requests>=2.31.0, pyyaml>=6.0, python-dotenv>=1.0.0, pytest>=8.0.0, pytest-mock>=3.14.0

---

## Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `config.yaml`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`
- Create: `scripts/` (dir)
- Create: `skill/scripts/` (dir)
- Create: `logs/` (dir)

**Step 1: Create requirements.txt**

```
py-clob-client==0.29.0
web3==6.14.0
anthropic>=0.40.0
requests>=2.31.0
pyyaml>=6.0
python-dotenv>=1.0.0
pytest>=8.0.0
pytest-mock>=3.14.0
```

**Step 2: Create .env.example**

```
POLYGON_PRIVATE_KEY=0x_your_64_char_hex_private_key
POLYMARKET_FUNDER_ADDRESS=0x_your_wallet_address_42_chars
ANTHROPIC_API_KEY=sk-ant-your_key_here
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_CHAT_ID=your_numeric_chat_id
```

**Step 3: Create .gitignore**

```
.env
logs/*.log
__pycache__/
*.pyc
.pytest_cache/
```

**Step 4: Create config.yaml**

```yaml
trading:
  dry_run: true
  interval_minutes: 30
  max_bet_usdc: 5.0
  max_daily_loss_usdc: 50.0
  min_confidence: 0.70

markets:
  min_volume_usdc: 1000
  max_markets_to_analyze: 20
```

**Step 5: Create directories and empty init files**

```bash
mkdir -p src tests scripts skill/scripts logs
touch src/__init__.py tests/__init__.py logs/.gitkeep
```

**Step 6: Install Python dependencies**

```bash
pip install -r requirements.txt
```

Expected: all packages install without errors. `py-clob-client` and `web3==6.14.0` must be pinned together to avoid conflicts.

**Step 7: Commit**

```bash
git add requirements.txt .env.example .gitignore config.yaml src/__init__.py tests/__init__.py logs/.gitkeep
git commit -m "feat: scaffold project structure"
```

---

## Task 2: Polymarket Client (TDD)

**Files:**
- Create: `tests/test_polymarket.py`
- Create: `src/polymarket.py`

**Step 1: Write the failing tests**

`tests/test_polymarket.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_polymarket.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.polymarket'`

**Step 3: Implement src/polymarket.py**

```python
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
        return self._clob.get_orders(OpenOrderParams())
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_polymarket.py -v
```

Expected: 4 tests PASSED.

**Step 5: Commit**

```bash
git add src/polymarket.py tests/test_polymarket.py
git commit -m "feat: add Polymarket CLOB client with dry-run support"
```

---

## Task 3: Claude Market Analyzer (TDD)

**Files:**
- Create: `tests/test_analysis.py`
- Create: `src/analysis.py`

**Step 1: Write the failing tests**

`tests/test_analysis.py`:

```python
import json
import pytest
from unittest.mock import patch, MagicMock

SAMPLE_MARKETS = [
    {
        "condition_id": "abc123",
        "question": "Will the Fed cut rates in March 2026?",
        "outcomes": ["Yes", "No"],
        "outcome_prices": ["0.72", "0.28"],
        "volume": 50000.0,
        "token_ids": ["tok_yes", "tok_no"],
    }
]

SAMPLE_RESPONSE = json.dumps({
    "decisions": [
        {
            "condition_id": "abc123",
            "action": "BUY_YES",
            "token_id": "tok_yes",
            "confidence": 0.80,
            "amount_usdc": 4.0,
            "reasoning": "Fed has signaled cuts; market underprices at 0.72",
        }
    ]
})


def _make_analyzer(response_text):
    with patch("src.analysis.anthropic.Anthropic") as MockAnthropic:
        instance = MockAnthropic.return_value
        msg = MagicMock()
        msg.content = [MagicMock(text=response_text)]
        instance.messages.create.return_value = msg
        from src.analysis import MarketAnalyzer
        return MarketAnalyzer(api_key="fake"), instance


def test_analyze_returns_decisions():
    analyzer, _ = _make_analyzer(SAMPLE_RESPONSE)
    decisions = analyzer.analyze(SAMPLE_MARKETS, max_bet_usdc=5.0, min_confidence=0.70)

    assert len(decisions) == 1
    assert decisions[0]["action"] == "BUY_YES"
    assert decisions[0]["token_id"] == "tok_yes"


def test_analyze_filters_low_confidence():
    low_conf = json.dumps({"decisions": [
        {"condition_id": "abc123", "action": "BUY_YES", "token_id": "tok_yes",
         "confidence": 0.50, "amount_usdc": 4.0, "reasoning": "not sure"}
    ]})
    analyzer, _ = _make_analyzer(low_conf)
    decisions = analyzer.analyze(SAMPLE_MARKETS, max_bet_usdc=5.0, min_confidence=0.70)

    assert decisions == []


def test_analyze_clamps_amount_to_max_bet():
    over_bet = json.dumps({"decisions": [
        {"condition_id": "abc123", "action": "BUY_YES", "token_id": "tok_yes",
         "confidence": 0.90, "amount_usdc": 999.0, "reasoning": "very sure"}
    ]})
    analyzer, _ = _make_analyzer(over_bet)
    decisions = analyzer.analyze(SAMPLE_MARKETS, max_bet_usdc=5.0, min_confidence=0.70)

    assert decisions[0]["amount_usdc"] == 5.0


def test_analyze_returns_empty_list_on_invalid_json():
    analyzer, _ = _make_analyzer("this is not json at all")
    decisions = analyzer.analyze(SAMPLE_MARKETS, max_bet_usdc=5.0, min_confidence=0.70)

    assert decisions == []


def test_analyze_returns_empty_list_for_no_markets():
    analyzer, mock_client = _make_analyzer(SAMPLE_RESPONSE)
    decisions = analyzer.analyze([], max_bet_usdc=5.0, min_confidence=0.70)

    mock_client.messages.create.assert_not_called()
    assert decisions == []
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_analysis.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.analysis'`

**Step 3: Implement src/analysis.py**

```python
import json
import anthropic

_SYSTEM_PROMPT = """\
You are a professional prediction market analyst on Polymarket.

Analyze the provided markets and decide which ones to bet on.
Respond ONLY with valid JSON matching this exact schema — no markdown, no extra text:

{
  "decisions": [
    {
      "condition_id": "<market condition_id from input>",
      "action": "BUY_YES" | "BUY_NO",
      "token_id": "<token_id for the chosen outcome>",
      "confidence": <float 0.0–1.0>,
      "amount_usdc": <float, suggested dollar amount>,
      "reasoning": "<one concise sentence>"
    }
  ]
}

Only include markets you want to bet on. Return {"decisions": []} if none qualify.
Be conservative — only bet where you have a clear informational edge.
"""


class MarketAnalyzer:
    def __init__(self, api_key: str):
        self._client = anthropic.Anthropic(api_key=api_key)

    def analyze(
        self, markets: list[dict], max_bet_usdc: float, min_confidence: float
    ) -> list[dict]:
        if not markets:
            return []

        user_msg = (
            f"Analyze these Polymarket markets. Max bet per market: ${max_bet_usdc}.\n\n"
            + json.dumps(markets, indent=2)
        )
        try:
            resp = self._client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            data = json.loads(resp.content[0].text)
        except Exception:
            return []

        decisions = []
        for d in data.get("decisions", []):
            if d.get("confidence", 0) < min_confidence:
                continue
            d["amount_usdc"] = min(float(d.get("amount_usdc", 0)), max_bet_usdc)
            decisions.append(d)
        return decisions
```

**Step 4: Run to verify pass**

```bash
python -m pytest tests/test_analysis.py -v
```

Expected: 5 tests PASSED.

**Step 5: Commit**

```bash
git add src/analysis.py tests/test_analysis.py
git commit -m "feat: add Claude-powered market analyzer"
```

---

## Task 4: Telegram Notifier (TDD)

**Files:**
- Create: `tests/test_notifier.py`
- Create: `src/notifier.py`

**Step 1: Write the failing tests**

`tests/test_notifier.py`:

```python
from unittest.mock import patch, MagicMock


def _make_notifier():
    from src.notifier import TelegramNotifier
    return TelegramNotifier(bot_token="test_token", chat_id="123456")


def test_send_posts_to_telegram_api():
    with patch("src.notifier.requests.post") as mock_post:
        mock_post.return_value.ok = True
        notifier = _make_notifier()
        notifier.send("Hello from trader")

    mock_post.assert_called_once()
    payload = mock_post.call_args.kwargs["json"]
    assert payload["chat_id"] == "123456"
    assert "Hello from trader" in payload["text"]


def test_send_trade_alert_includes_dry_run_prefix():
    with patch("src.notifier.requests.post") as mock_post:
        mock_post.return_value.ok = True
        notifier = _make_notifier()
        notifier.send_trade_alert(
            question="Will Fed cut rates?",
            action="BUY_YES",
            amount_usdc=4.0,
            confidence=0.80,
            reasoning="Fed signaled cuts",
            dry_run=True,
        )

    text = mock_post.call_args.kwargs["json"]["text"]
    assert "[DRY RUN]" in text
    assert "BUY YES" in text
    assert "$4.00" in text
    assert "80%" in text


def test_send_trade_alert_no_prefix_when_live():
    with patch("src.notifier.requests.post") as mock_post:
        mock_post.return_value.ok = True
        notifier = _make_notifier()
        notifier.send_trade_alert(
            question="Q", action="BUY_NO", amount_usdc=3.0,
            confidence=0.75, reasoning="reason", dry_run=False,
        )

    text = mock_post.call_args.kwargs["json"]["text"]
    assert "[DRY RUN]" not in text
    assert "BUY NO" in text


def test_send_cycle_summary_includes_counts():
    with patch("src.notifier.requests.post") as mock_post:
        mock_post.return_value.ok = True
        notifier = _make_notifier()
        notifier.send_cycle_summary(
            markets_analyzed=20, bets_placed=2, total_usdc=8.0, dry_run=True
        )

    text = mock_post.call_args.kwargs["json"]["text"]
    assert "20" in text
    assert "2" in text
    assert "$8.00" in text
    assert "[DRY RUN]" in text
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_notifier.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.notifier'`

**Step 3: Implement src/notifier.py**

```python
import requests


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id

    def send(self, text: str) -> None:
        requests.post(
            self._url,
            json={"chat_id": self._chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )

    def send_trade_alert(
        self,
        question: str,
        action: str,
        amount_usdc: float,
        confidence: float,
        reasoning: str,
        dry_run: bool,
    ) -> None:
        prefix = "[DRY RUN] " if dry_run else ""
        side = "YES" if action == "BUY_YES" else "NO"
        self.send(
            f"{prefix}*Trade Alert*\n"
            f"Market: {question}\n"
            f"Action: BUY {side}\n"
            f"Amount: ${amount_usdc:.2f}\n"
            f"Confidence: {confidence:.0%}\n"
            f"Reason: {reasoning}"
        )

    def send_cycle_summary(
        self,
        markets_analyzed: int,
        bets_placed: int,
        total_usdc: float,
        dry_run: bool,
    ) -> None:
        prefix = "[DRY RUN] " if dry_run else ""
        self.send(
            f"{prefix}*Cycle Summary*\n"
            f"Markets analyzed: {markets_analyzed}\n"
            f"Bets placed: {bets_placed}\n"
            f"Total wagered: ${total_usdc:.2f}"
        )
```

**Step 4: Run to verify pass**

```bash
python -m pytest tests/test_notifier.py -v
```

Expected: 4 tests PASSED.

**Step 5: Commit**

```bash
git add src/notifier.py tests/test_notifier.py
git commit -m "feat: add Telegram notifier with trade and summary alerts"
```

---

## Task 5: Trading Cycle Orchestrator (TDD)

**Files:**
- Create: `tests/test_cycle.py`
- Create: `src/cycle.py`

**Step 1: Write the failing tests**

`tests/test_cycle.py`:

```python
from unittest.mock import MagicMock

MARKETS = [
    {
        "condition_id": "abc123",
        "question": "Will Fed cut rates in March 2026?",
        "outcomes": ["Yes", "No"],
        "outcome_prices": ["0.72", "0.28"],
        "volume": 50000.0,
        "token_ids": ["tok_yes", "tok_no"],
    }
]

DECISIONS = [
    {
        "condition_id": "abc123",
        "action": "BUY_YES",
        "token_id": "tok_yes",
        "confidence": 0.80,
        "amount_usdc": 4.0,
        "reasoning": "Fed signaled cuts",
    }
]


def _make_cycle(dry_run=True):
    from src.cycle import TradingCycle
    poly = MagicMock()
    analyzer = MagicMock()
    notifier = MagicMock()
    cycle = TradingCycle(
        poly, analyzer, notifier,
        dry_run=dry_run, max_bet_usdc=5.0, min_confidence=0.70
    )
    return cycle, poly, analyzer, notifier


def test_cycle_fetches_markets_and_runs_analysis():
    cycle, poly, analyzer, _ = _make_cycle()
    poly.get_open_markets.return_value = MARKETS
    analyzer.analyze.return_value = DECISIONS

    cycle.run()

    poly.get_open_markets.assert_called_once()
    analyzer.analyze.assert_called_once_with(
        MARKETS, max_bet_usdc=5.0, min_confidence=0.70
    )


def test_cycle_sends_alert_per_decision():
    cycle, poly, analyzer, notifier = _make_cycle(dry_run=True)
    poly.get_open_markets.return_value = MARKETS
    analyzer.analyze.return_value = DECISIONS

    cycle.run()

    notifier.send_trade_alert.assert_called_once()
    kw = notifier.send_trade_alert.call_args.kwargs
    assert kw["dry_run"] is True
    assert kw["action"] == "BUY_YES"
    assert kw["amount_usdc"] == 4.0


def test_cycle_dry_run_skips_place_order():
    cycle, poly, analyzer, _ = _make_cycle(dry_run=True)
    poly.get_open_markets.return_value = MARKETS
    analyzer.analyze.return_value = DECISIONS

    cycle.run()

    poly.place_market_order.assert_not_called()


def test_cycle_live_calls_place_order():
    cycle, poly, analyzer, _ = _make_cycle(dry_run=False)
    poly.get_open_markets.return_value = MARKETS
    analyzer.analyze.return_value = DECISIONS
    poly.place_market_order.return_value = {"order_id": "ord_1"}

    cycle.run()

    poly.place_market_order.assert_called_once_with(
        token_id="tok_yes", amount_usdc=4.0, dry_run=False
    )


def test_cycle_sends_summary_with_correct_counts():
    cycle, poly, analyzer, notifier = _make_cycle(dry_run=True)
    poly.get_open_markets.return_value = MARKETS
    analyzer.analyze.return_value = DECISIONS

    result = cycle.run()

    notifier.send_cycle_summary.assert_called_once()
    kw = notifier.send_cycle_summary.call_args.kwargs
    assert kw["bets_placed"] == 1
    assert kw["total_usdc"] == 4.0
    assert kw["markets_analyzed"] == 1
    assert result == {"bets_placed": 1, "total_usdc": 4.0}
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_cycle.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.cycle'`

**Step 3: Implement src/cycle.py**

```python
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
```

**Step 4: Run all tests**

```bash
python -m pytest tests/ -v
```

Expected: all 18 tests PASSED.

**Step 5: Commit**

```bash
git add src/cycle.py tests/test_cycle.py
git commit -m "feat: add trading cycle orchestrator"
```

---

## Task 6: CLI Entry Point

**Files:**
- Create: `scripts/run_cycle.py`

**Step 1: Create scripts/run_cycle.py**

```python
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
```

**Step 2: Make executable**

```bash
chmod +x scripts/run_cycle.py
```

**Step 3: Commit**

```bash
git add scripts/run_cycle.py
git commit -m "feat: add CLI entry point for launchd scheduler"
```

---

## Task 7: Install OpenClaw

**Step 1: Verify Node.js 22+**

```bash
node --version
```

If below v22, install via nvm:

```bash
nvm install 22 && nvm use 22
```

**Step 2: Install OpenClaw globally**

```bash
npm install -g openclaw@latest
openclaw --version
```

Expected: prints a version number like `openclaw/x.y.z`.

**Step 3: Run onboarding**

```bash
openclaw onboard --install-daemon
```

When prompted:
- Select **Telegram** as the messaging channel
- Enter your Telegram bot token
- Skip other channels for now

Onboarding configures `~/.openclaw/openclaw.json` and starts the background daemon.

---

## Task 8: Create OpenClaw Skill

**Files:**
- Create: `skill/SKILL.md`
- Create: `skill/scripts/trigger_cycle.py`
- Create: `skill/scripts/query_portfolio.py`

**Step 1: Create skill/SKILL.md**

```markdown
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
```

**Step 2: Create skill/scripts/trigger_cycle.py**

```python
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
```

**Step 3: Create skill/scripts/query_portfolio.py**

```python
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
```

**Step 4: Make scripts executable**

```bash
chmod +x skill/scripts/trigger_cycle.py skill/scripts/query_portfolio.py
```

**Step 5: Symlink skill into OpenClaw workspace**

```bash
mkdir -p ~/.openclaw/workspace/skills
ln -s /Users/tomerab/dev/trader/skill ~/.openclaw/workspace/skills/ai-polymarket-trader
```

**Step 6: Reload and verify skill is registered**

```bash
openclaw agent --message "refresh skills"
openclaw skills list
```

Expected: `ai-polymarket-trader` appears in the skill list.

**Step 7: Commit**

```bash
git add skill/
git commit -m "feat: add OpenClaw skill for interactive trading queries"
```

---

## Task 9: Wallet & Credentials Setup (Manual)

> These steps require real accounts. Complete before Task 10.

**Step 1: Generate a Polygon EOA wallet**

```bash
python3 - <<'EOF'
from web3 import Web3
acct = Web3().eth.account.create()
print("Address:     ", acct.address)
print("Private key: ", acct.key.hex())
EOF
```

Save the output. This is your Polygon wallet. Keep the private key secret.

**Step 2: Fund with USDC on Polygon**

- Buy USDC on Coinbase → withdraw to Polygon network to your new address
- Or bridge existing ETH/USDC via [wallet.polygon.technology](https://wallet.polygon.technology)
- Start with $20–50 USDC for testing

**Step 3: Get a Polymarket API key**

1. Go to [polymarket.com](https://polymarket.com) → connect your wallet (import private key into MetaMask)
2. Navigate to Account → API → Generate API credentials
3. Note the API key and secret

**Step 4: Create a Telegram bot**

1. Open Telegram → search `@BotFather` → send `/newbot`
2. Follow prompts → copy the bot token
3. Send any message to your new bot
4. Get your chat ID: `curl "https://api.telegram.org/bot<TOKEN>/getUpdates"` → find `"chat":{"id":...}`

**Step 5: Fill in .env**

```bash
cp .env.example .env
# Edit .env with your actual values using any text editor
nano .env
```

Verify all 5 variables are set:

```bash
python3 -c "
from dotenv import load_dotenv; import os; load_dotenv()
keys = ['POLYGON_PRIVATE_KEY','POLYMARKET_FUNDER_ADDRESS','ANTHROPIC_API_KEY','TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID']
for k in keys: print(k, '✓' if os.getenv(k) else '✗ MISSING')
"
```

Expected: all 5 show ✓.

---

## Task 10: Set Up Automated Schedule (launchd)

**Step 1: Create the launchd plist**

```bash
cat > ~/Library/LaunchAgents/com.trader.cycle.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trader.cycle</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/tomerab/dev/trader/scripts/run_cycle.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/tomerab/dev/trader</string>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>StandardOutPath</key>
    <string>/Users/tomerab/dev/trader/logs/cycle.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/tomerab/dev/trader/logs/cycle_error.log</string>
    <key>RunAtLoad</key>
    <false/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF
```

**Step 2: Load the job**

```bash
launchctl load ~/Library/LaunchAgents/com.trader.cycle.plist
launchctl list | grep com.trader
```

Expected: a line with `com.trader.cycle` and `0` exit code (no errors).

**Step 3: Copy plist to project for version control**

```bash
cp ~/Library/LaunchAgents/com.trader.cycle.plist com.trader.cycle.plist
echo "logs/*.log" >> .gitignore
git add com.trader.cycle.plist .gitignore
git commit -m "feat: add launchd plist for 30-minute automated schedule"
```

---

## Task 11: End-to-End Dry Run Verification

**Step 1: Confirm dry_run is true in config.yaml**

```bash
grep dry_run config.yaml
```

Expected: `dry_run: true`

**Step 2: Run the cycle manually**

```bash
python3 scripts/run_cycle.py
```

Expected terminal output:
```
Cycle complete: bets_placed=N, total_usdc=$X.XX
```

(N may be 0 if Claude finds no good bets — that is correct.)

**Step 3: Verify Telegram messages**

Open Telegram → your bot. You should see:
- Zero or more `[DRY RUN] Trade Alert` messages (one per bet decision)
- One `[DRY RUN] Cycle Summary` message

**Step 4: Trigger via OpenClaw chat**

In Telegram, message your OpenClaw bot:
```
run a trading cycle
```

Expected: OpenClaw invokes the skill, runs the script, and replies with the result in chat.

**Step 5: Verify no real orders on Polymarket**

Log into [polymarket.com](https://polymarket.com) → your account → open orders. Should be empty (dry run mode).

**Step 6: Final all-tests pass check**

```bash
python -m pytest tests/ -v
```

Expected: 18 tests PASSED, 0 failed.

---

## Summary

| Task | What gets built |
|------|----------------|
| 1 | Project scaffold, config, deps |
| 2 | Polymarket CLOB client |
| 3 | Claude market analyzer |
| 4 | Telegram notifier |
| 5 | Trading cycle orchestrator |
| 6 | CLI entry point |
| 7 | OpenClaw installed |
| 8 | OpenClaw skill (interactive queries) |
| 9 | Wallet + API credentials |
| 10 | launchd auto-schedule |
| 11 | End-to-end dry run verified |

**When you're ready to go live:** edit `config.yaml`, set `dry_run: false`.
