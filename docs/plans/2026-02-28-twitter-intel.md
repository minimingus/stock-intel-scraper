# Twitter Intel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Playwright-based Twitter monitoring system that tracks trading experts, extracts stock/crypto/Polymarket signals via Claude, and delivers a daily Telegram brief at 8am.

**Architecture:** A single APScheduler process scrapes expert timelines every 4h via Playwright, stores raw tweets in SQLite, runs Claude signal extraction after each scrape, and synthesizes a daily brief at 8am via Telegram. Auto-discovery finds new expert handles from @mentions in collected tweets.

**Tech Stack:** Python 3.11+, playwright>=1.45.0, apscheduler>=3.10.0, sqlite3 (stdlib), anthropic>=0.40.0, requests>=2.31.0, pyyaml>=6.0, pytest>=8.0.0, pytest-mock>=3.14.0

---

## Task 1: Scaffold — deps, dirs, config

**Files:**
- Modify: `requirements.txt`
- Modify: `config.yaml`
- Modify: `.gitignore` (if exists, else create)
- Create: `data/.gitkeep`
- Create: `src/twitter_intel/__init__.py`
- Create: `tests/test_twitter_intel/__init__.py`

**Step 1: Add new dependencies to requirements.txt**

Append to the existing `requirements.txt`:
```
playwright>=1.45.0
apscheduler>=3.10.0
```

**Step 2: Add twitter_intel section to config.yaml**

Append to the existing `config.yaml`:
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

**Step 3: Update .gitignore**

Add these lines (create file if missing):
```
data/twitter_intel.db
logs/brief-*.txt
```

**Step 4: Create directories and empty init files**

```bash
mkdir -p data src/twitter_intel tests/test_twitter_intel
touch data/.gitkeep src/twitter_intel/__init__.py tests/test_twitter_intel/__init__.py
```

**Step 5: Install new dependencies**

```bash
pip install playwright apscheduler
playwright install chromium
```

Expected: no errors. `playwright --version` prints a version string.

**Step 6: Commit**

```bash
git add requirements.txt config.yaml .gitignore data/.gitkeep src/twitter_intel/__init__.py tests/test_twitter_intel/__init__.py
git commit -m "chore: scaffold twitter intel module"
```

---

## Task 2: SQLite Store

**Files:**
- Create: `src/twitter_intel/store.py`
- Create: `tests/test_twitter_intel/test_store.py`

**Step 1: Write the failing tests**

Create `tests/test_twitter_intel/test_store.py`:
```python
import pytest
from src.twitter_intel.store import TwitterIntelStore


@pytest.fixture
def store(tmp_path):
    return TwitterIntelStore(db_path=str(tmp_path / "test.db"))


def test_upsert_expert_and_retrieve(store):
    store.upsert_expert("trader1", source="seed")
    store.upsert_expert("trader2", source="discovered")
    experts = store.get_active_experts()
    assert "trader1" in experts
    assert "trader2" in experts


def test_upsert_expert_is_idempotent(store):
    store.upsert_expert("trader1")
    store.upsert_expert("trader1")
    assert store.get_active_experts().count("trader1") == 1


def test_insert_tweet_appears_in_new_tweets(store):
    store.upsert_expert("trader1")
    store.insert_tweet("t1", "trader1", "BTC going to 100k", 10, 5)
    new = store.get_new_tweets()
    assert len(new) == 1
    assert new[0]["tweet_id"] == "t1"


def test_tweet_disappears_from_new_after_signal_inserted(store):
    store.upsert_expert("trader1")
    store.insert_tweet("t1", "trader1", "BTC going to 100k", 10, 5)
    store.insert_signal("t1", "BTC", "crypto", "bullish")
    new = store.get_new_tweets()
    assert len(new) == 0


def test_get_signals_for_brief_ranks_by_expert_count(store):
    store.upsert_expert("a")
    store.upsert_expert("b")
    store.insert_tweet("t1", "a", "BTC", 0, 0)
    store.insert_tweet("t2", "b", "BTC", 0, 0)
    store.insert_tweet("t3", "a", "ETH", 0, 0)
    store.insert_signal("t1", "BTC", "crypto", "bullish")
    store.insert_signal("t2", "BTC", "crypto", "bullish")
    store.insert_signal("t3", "ETH", "crypto", "neutral")
    signals = store.get_signals_for_brief(24)
    assert signals[0]["ticker"] == "BTC"
    assert signals[0]["expert_count"] == 2
    assert signals[1]["ticker"] == "ETH"


def test_prune_old_tweets_removes_stale_rows(store):
    store.upsert_expert("a")
    store.insert_tweet("t1", "a", "old tweet", 0, 0)
    store.conn.execute(
        "UPDATE tweets SET scraped_at = '2020-01-01T00:00:00+00:00' WHERE tweet_id = 't1'"
    )
    store.conn.commit()
    store.prune_old_tweets(days=7)
    assert len(store.get_new_tweets()) == 0


def test_get_expert_count(store):
    store.upsert_expert("a")
    store.upsert_expert("b")
    assert store.get_expert_count() == 2


def test_get_tweet_count_24h(store):
    store.upsert_expert("a")
    store.insert_tweet("t1", "a", "recent", 0, 0)
    assert store.get_tweet_count_24h() == 1
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_twitter_intel/test_store.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.twitter_intel.store'`

**Step 3: Implement `src/twitter_intel/store.py`**

```python
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class TwitterIntelStore:
    def __init__(self, db_path: str = "data/twitter_intel.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS experts (
                handle      TEXT PRIMARY KEY,
                source      TEXT NOT NULL,
                added_date  TEXT NOT NULL,
                active      INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS tweets (
                tweet_id    TEXT PRIMARY KEY,
                handle      TEXT NOT NULL,
                text        TEXT NOT NULL,
                likes       INTEGER NOT NULL DEFAULT 0,
                retweets    INTEGER NOT NULL DEFAULT 0,
                scraped_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS signals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                tweet_id     TEXT NOT NULL,
                ticker       TEXT NOT NULL,
                asset_type   TEXT NOT NULL,
                sentiment    TEXT NOT NULL,
                extracted_at TEXT NOT NULL
            );
        """)
        self.conn.commit()

    def upsert_expert(self, handle: str, source: str = "seed"):
        self.conn.execute(
            "INSERT OR IGNORE INTO experts (handle, source, added_date, active) VALUES (?, ?, ?, 1)",
            (handle, source, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def get_active_experts(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT handle FROM experts WHERE active = 1"
        ).fetchall()
        return [r["handle"] for r in rows]

    def insert_tweet(self, tweet_id: str, handle: str, text: str, likes: int, retweets: int):
        self.conn.execute(
            "INSERT OR IGNORE INTO tweets (tweet_id, handle, text, likes, retweets, scraped_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tweet_id, handle, text, likes, retweets, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def get_new_tweets(self) -> list[dict]:
        """Return tweets not yet processed by signal extraction."""
        rows = self.conn.execute("""
            SELECT t.tweet_id, t.handle, t.text FROM tweets t
            LEFT JOIN signals s ON s.tweet_id = t.tweet_id
            WHERE s.tweet_id IS NULL
        """).fetchall()
        return [dict(r) for r in rows]

    def insert_signal(self, tweet_id: str, ticker: str, asset_type: str, sentiment: str):
        self.conn.execute(
            "INSERT INTO signals (tweet_id, ticker, asset_type, sentiment, extracted_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (tweet_id, ticker, asset_type, sentiment, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def get_signals_for_brief(self, lookback_hours: int = 24) -> list[dict]:
        """Ranked signals: tickers mentioned by most distinct experts in the window."""
        rows = self.conn.execute("""
            SELECT s.ticker, s.asset_type,
                   COUNT(DISTINCT t.handle) AS expert_count,
                   GROUP_CONCAT(DISTINCT t.handle) AS experts,
                   SUM(CASE WHEN s.sentiment = 'bullish' THEN 1 ELSE 0 END) AS bullish_count,
                   SUM(CASE WHEN s.sentiment = 'bearish' THEN 1 ELSE 0 END) AS bearish_count
            FROM signals s
            JOIN tweets t ON t.tweet_id = s.tweet_id
            WHERE s.extracted_at >= datetime('now', ?)
            GROUP BY s.ticker, s.asset_type
            ORDER BY expert_count DESC
        """, (f"-{lookback_hours} hours",)).fetchall()
        return [dict(r) for r in rows]

    def prune_old_tweets(self, days: int = 7):
        self.conn.execute(
            "DELETE FROM tweets WHERE scraped_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        self.conn.commit()

    def get_expert_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM experts WHERE active = 1"
        ).fetchone()[0]

    def get_tweet_count_24h(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM tweets WHERE scraped_at >= datetime('now', '-24 hours')"
        ).fetchone()[0]
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_twitter_intel/test_store.py -v
```
Expected: 8 tests PASSED.

**Step 5: Commit**

```bash
git add src/twitter_intel/store.py tests/test_twitter_intel/test_store.py
git commit -m "feat: add SQLite store for twitter intel"
```

---

## Task 3: Playwright Scraper

**Files:**
- Create: `src/twitter_intel/scraper.py`
- Create: `tests/test_twitter_intel/test_scraper.py`

**Step 1: Write the failing tests**

Create `tests/test_twitter_intel/test_scraper.py`:
```python
from unittest.mock import MagicMock, patch
import pytest
from src.twitter_intel.scraper import TwitterScraper, _parse_count


# --- Unit tests for _parse_count helper ---

def test_parse_count_plain_integer():
    assert _parse_count("34") == 34

def test_parse_count_k_suffix():
    assert _parse_count("1.2K") == 1200

def test_parse_count_m_suffix():
    assert _parse_count("5.6M") == 5_600_000

def test_parse_count_empty_string():
    assert _parse_count("") == 0

def test_parse_count_with_comma():
    assert _parse_count("1,234") == 1234


# --- Behavioural tests for TwitterScraper ---

def _make_playwright_mock(login_wall: bool = False):
    """Build a mock sync_playwright context manager."""
    mock_page = MagicMock()
    # locator('[data-testid="loginButton"]').count()
    login_locator = MagicMock()
    login_locator.count.return_value = 1 if login_wall else 0

    tweet_locator = MagicMock()
    tweet_locator.all.return_value = []

    def locator_side_effect(selector):
        if "loginButton" in selector:
            return login_locator
        return tweet_locator

    mock_page.locator.side_effect = locator_side_effect

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_p = MagicMock()
    mock_p.chromium.launch.return_value = mock_browser

    mock_pw = MagicMock()
    mock_pw.__enter__ = MagicMock(return_value=mock_p)
    mock_pw.__exit__ = MagicMock(return_value=False)
    return mock_pw


def test_scrape_handle_returns_empty_on_login_wall():
    mock_pw = _make_playwright_mock(login_wall=True)
    with patch("src.twitter_intel.scraper.sync_playwright", return_value=mock_pw):
        scraper = TwitterScraper()
        result = scraper.scrape_handle("testuser")
    assert result == []


def test_scrape_handle_returns_empty_on_exception():
    with patch("src.twitter_intel.scraper.sync_playwright", side_effect=Exception("crash")):
        scraper = TwitterScraper()
        result = scraper.scrape_handle("testuser")
    assert result == []


def test_scrape_all_aggregates_results():
    mock_pw = _make_playwright_mock(login_wall=False)
    with patch("src.twitter_intel.scraper.sync_playwright", return_value=mock_pw):
        scraper = TwitterScraper()
        results = scraper.scrape_all(["user1", "user2"])
    assert "user1" in results
    assert "user2" in results
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_twitter_intel/test_scraper.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.twitter_intel.scraper'`

**Step 3: Implement `src/twitter_intel/scraper.py`**

```python
import logging
from playwright.sync_api import sync_playwright, Page

logger = logging.getLogger(__name__)


def _parse_count(text: str) -> int:
    """Parse display counts: '1.2K' → 1200, '5.6M' → 5_600_000, '34' → 34."""
    text = text.strip().replace(",", "")
    if not text:
        return 0
    try:
        if text.upper().endswith("K"):
            return int(float(text[:-1]) * 1_000)
        if text.upper().endswith("M"):
            return int(float(text[:-1]) * 1_000_000)
        return int(float(text))
    except ValueError:
        return 0


def _extract_tweets_from_page(page: Page) -> list[dict]:
    tweets = []
    for el in page.locator('[data-testid="tweet"]').all():
        text_el = el.locator('[data-testid="tweetText"]')
        text = text_el.inner_text() if text_el.count() > 0 else ""
        if not text:
            continue

        tweet_id = ""
        for link in el.locator('a[href*="/status/"]').all():
            href = link.get_attribute("href") or ""
            if "/status/" in href:
                tweet_id = href.split("/status/")[1].split("/")[0].split("?")[0]
                break
        if not tweet_id:
            continue

        like_el = el.locator('[data-testid="like"] span')
        likes_text = like_el.inner_text() if like_el.count() > 0 else "0"
        rt_el = el.locator('[data-testid="retweet"] span')
        rt_text = rt_el.inner_text() if rt_el.count() > 0 else "0"

        tweets.append({
            "tweet_id": tweet_id,
            "text": text,
            "likes": _parse_count(likes_text),
            "retweets": _parse_count(rt_text),
        })
    return tweets


class TwitterScraper:
    def scrape_handle(self, handle: str) -> list[dict]:
        """Scrape recent tweets for a handle. Returns list of tweet dicts."""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                page = context.new_page()
                try:
                    page.goto(
                        f"https://x.com/{handle}",
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                    if page.locator('[data-testid="loginButton"]').count() > 0:
                        logger.warning("Login wall for @%s, skipping", handle)
                        return []
                    page.wait_for_selector('[data-testid="tweet"]', timeout=15_000)
                    return _extract_tweets_from_page(page)
                except Exception as e:
                    logger.warning("Failed to scrape @%s: %s", handle, e)
                    return []
                finally:
                    browser.close()
        except Exception as e:
            logger.warning("Playwright error for @%s: %s", handle, e)
            return []

    def scrape_all(self, handles: list[str]) -> dict[str, list[dict]]:
        """Scrape multiple handles. Returns {handle: [tweets]}."""
        results = {}
        for handle in handles:
            results[handle] = self.scrape_handle(handle)
            logger.info("Scraped @%s: %d tweets", handle, len(results[handle]))
        return results
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_twitter_intel/test_scraper.py -v
```
Expected: 7 tests PASSED.

**Step 5: Commit**

```bash
git add src/twitter_intel/scraper.py tests/test_twitter_intel/test_scraper.py
git commit -m "feat: add Playwright scraper for twitter intel"
```

---

## Task 4: Claude Signal Extractor

**Files:**
- Create: `src/twitter_intel/extractor.py`
- Create: `tests/test_twitter_intel/test_extractor.py`

**Step 1: Write the failing tests**

Create `tests/test_twitter_intel/test_extractor.py`:
```python
import json
import pytest
from unittest.mock import MagicMock, patch
from src.twitter_intel.extractor import SignalExtractor
from src.twitter_intel.store import TwitterIntelStore


@pytest.fixture
def store(tmp_path):
    s = TwitterIntelStore(db_path=str(tmp_path / "test.db"))
    s.upsert_expert("trader1")
    s.insert_tweet("t1", "trader1", "$BTC breaking $90k, very bullish", 10, 5)
    return s


def _mock_claude(response_json: list):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=json.dumps(response_json))]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


def test_extract_batch_inserts_signals(store):
    mock_client = _mock_claude([
        {"tweet_id": "t1", "ticker": "BTC", "asset_type": "crypto", "sentiment": "bullish"}
    ])
    with patch("src.twitter_intel.extractor.Anthropic", return_value=mock_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        extractor = SignalExtractor(store)
        count = extractor.extract_batch([{"tweet_id": "t1", "text": "$BTC bullish"}])
    assert count == 1
    signals = store.get_signals_for_brief(24)
    assert signals[0]["ticker"] == "BTC"


def test_extract_batch_uppercases_ticker(store):
    mock_client = _mock_claude([
        {"tweet_id": "t1", "ticker": "btc", "asset_type": "crypto", "sentiment": "bullish"}
    ])
    with patch("src.twitter_intel.extractor.Anthropic", return_value=mock_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        extractor = SignalExtractor(store)
        extractor.extract_batch([{"tweet_id": "t1", "text": "btc"}])
    signals = store.get_signals_for_brief(24)
    assert signals[0]["ticker"] == "BTC"


def test_extract_batch_returns_zero_on_api_failure(store):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API error")
    with patch("src.twitter_intel.extractor.Anthropic", return_value=mock_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        extractor = SignalExtractor(store)
        count = extractor.extract_batch([{"tweet_id": "t1", "text": "test"}])
    assert count == 0


def test_extract_batch_skips_malformed_signal(store):
    mock_client = _mock_claude([
        {"tweet_id": "t1", "ticker": "BTC", "asset_type": "crypto", "sentiment": "bullish"},
        {"tweet_id": "t1"},  # missing required fields
    ])
    with patch("src.twitter_intel.extractor.Anthropic", return_value=mock_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        extractor = SignalExtractor(store)
        count = extractor.extract_batch([{"tweet_id": "t1", "text": "test"}])
    assert count == 1


def test_extract_batch_empty_input_returns_zero(store):
    with patch("src.twitter_intel.extractor.Anthropic"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        extractor = SignalExtractor(store)
        count = extractor.extract_batch([])
    assert count == 0


def test_run_processes_all_new_tweets(store):
    mock_client = _mock_claude([
        {"tweet_id": "t1", "ticker": "BTC", "asset_type": "crypto", "sentiment": "bullish"}
    ])
    with patch("src.twitter_intel.extractor.Anthropic", return_value=mock_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        extractor = SignalExtractor(store)
        count = extractor.run()
    assert count == 1
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_twitter_intel/test_extractor.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.twitter_intel.extractor'`

**Step 3: Implement `src/twitter_intel/extractor.py`**

```python
import json
import logging
import os

from anthropic import Anthropic

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
You are a financial signal extractor. Given tweets from trading experts, extract all mentions of:
- Stock tickers (e.g. NVDA, TSLA, AAPL)
- Crypto assets (e.g. BTC, ETH, SOL)
- Polymarket prediction markets (any prediction market question being discussed)

For each mention return one JSON object with:
  tweet_id   : string (copy from input)
  ticker     : string (the symbol or short name)
  asset_type : "stock" | "crypto" | "polymarket"
  sentiment  : "bullish" | "bearish" | "neutral"

Return ONLY a valid JSON array. No markdown. No explanation.
If a tweet has no clear financial signal, omit it entirely.

Tweets:
{tweets_json}"""


class SignalExtractor:
    def __init__(self, store: TwitterIntelStore):
        self.store = store
        self.client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def extract_batch(self, tweets: list[dict]) -> int:
        """Extract signals from a batch of tweets. Returns count of signals stored."""
        if not tweets:
            return 0

        tweets_json = json.dumps(
            [{"tweet_id": t["tweet_id"], "text": t["text"]} for t in tweets],
            ensure_ascii=False,
        )
        try:
            msg = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": _EXTRACTION_PROMPT.format(tweets_json=tweets_json),
                }],
            )
            signals = json.loads(msg.content[0].text.strip())
        except Exception as e:
            logger.error("Signal extraction failed: %s", e)
            return 0

        count = 0
        for sig in signals:
            try:
                self.store.insert_signal(
                    tweet_id=sig["tweet_id"],
                    ticker=sig["ticker"].upper(),
                    asset_type=sig["asset_type"],
                    sentiment=sig["sentiment"],
                )
                count += 1
            except (KeyError, Exception) as e:
                logger.warning("Skipping malformed signal %s: %s", sig, e)
        return count

    def run(self) -> int:
        """Extract signals from all unprocessed tweets in the store."""
        return self.extract_batch(self.store.get_new_tweets())
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_twitter_intel/test_extractor.py -v
```
Expected: 6 tests PASSED.

**Step 5: Commit**

```bash
git add src/twitter_intel/extractor.py tests/test_twitter_intel/test_extractor.py
git commit -m "feat: add Claude signal extractor for twitter intel"
```

---

## Task 5: Expert Auto-Discovery

**Files:**
- Create: `src/twitter_intel/discovery.py`
- Create: `tests/test_twitter_intel/test_discovery.py`

**Step 1: Write the failing tests**

Create `tests/test_twitter_intel/test_discovery.py`:
```python
import pytest
from src.twitter_intel.discovery import ExpertDiscovery
from src.twitter_intel.store import TwitterIntelStore


@pytest.fixture
def store(tmp_path):
    s = TwitterIntelStore(db_path=str(tmp_path / "test.db"))
    s.upsert_expert("seed1", source="seed")
    return s


def test_discover_finds_frequently_mentioned_handle(store):
    tweets = [
        {"tweet_id": f"t{i}", "text": "@newtrader bullish on BTC"} for i in range(3)
    ]
    discovery = ExpertDiscovery(store, max_accounts=100, min_interactions=3)
    new = discovery.discover_from_tweets(tweets)
    assert "newtrader" in new


def test_discover_ignores_below_threshold(store):
    tweets = [
        {"tweet_id": "t1", "text": "@rarehandle only mentioned once"}
    ]
    discovery = ExpertDiscovery(store, max_accounts=100, min_interactions=3)
    new = discovery.discover_from_tweets(tweets)
    assert "rarehandle" not in new


def test_discover_ignores_existing_experts(store):
    tweets = [
        {"tweet_id": f"t{i}", "text": "@seed1 great call"} for i in range(5)
    ]
    discovery = ExpertDiscovery(store, max_accounts=100, min_interactions=3)
    new = discovery.discover_from_tweets(tweets)
    assert "seed1" not in new


def test_discover_respects_max_accounts(store):
    # store already has 1 expert; max_accounts=1 → no room for new ones
    tweets = [
        {"tweet_id": f"t{i}", "text": "@newguy hot take"} for i in range(5)
    ]
    discovery = ExpertDiscovery(store, max_accounts=1, min_interactions=1)
    new = discovery.discover_from_tweets(tweets)
    assert len(new) == 0


def test_run_adds_discovered_experts_to_store(store):
    tweets = [
        {"tweet_id": f"t{i}", "text": "@discovered_expert signal"} for i in range(3)
    ]
    discovery = ExpertDiscovery(store, max_accounts=100, min_interactions=3)
    added = discovery.run(tweets)
    assert added == 1
    assert "discovered_expert" in store.get_active_experts()
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_twitter_intel/test_discovery.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.twitter_intel.discovery'`

**Step 3: Implement `src/twitter_intel/discovery.py`**

```python
import logging
import re
from collections import Counter

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)


class ExpertDiscovery:
    def __init__(self, store: TwitterIntelStore, max_accounts: int = 100, min_interactions: int = 3):
        self.store = store
        self.max_accounts = max_accounts
        self.min_interactions = min_interactions

    def discover_from_tweets(self, tweets: list[dict]) -> list[str]:
        """Find @handles that appear >= min_interactions times and aren't already tracked."""
        existing = {h.lower() for h in self.store.get_active_experts()}
        current_count = len(existing)

        mention_counts: Counter = Counter()
        for tweet in tweets:
            for handle in re.findall(r"@(\w+)", tweet.get("text", "")):
                if handle.lower() not in existing:
                    mention_counts[handle.lower()] += 1

        new_handles = []
        for handle, count in mention_counts.most_common():
            if current_count >= self.max_accounts:
                break
            if count >= self.min_interactions:
                new_handles.append(handle)
                current_count += 1
        return new_handles

    def run(self, recent_tweets: list[dict]) -> int:
        """Discover and persist new experts. Returns count added."""
        new_handles = self.discover_from_tweets(recent_tweets)
        for handle in new_handles:
            self.store.upsert_expert(handle, source="discovered")
            logger.info("Discovered new expert: @%s", handle)
        return len(new_handles)
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_twitter_intel/test_discovery.py -v
```
Expected: 5 tests PASSED.

**Step 5: Commit**

```bash
git add src/twitter_intel/discovery.py tests/test_twitter_intel/test_discovery.py
git commit -m "feat: add expert auto-discovery for twitter intel"
```

---

## Task 6: Brief Generator

**Files:**
- Create: `src/twitter_intel/brief.py`
- Create: `tests/test_twitter_intel/test_brief.py`

**Step 1: Write the failing tests**

Create `tests/test_twitter_intel/test_brief.py`:
```python
import pytest
from unittest.mock import MagicMock, patch
from src.twitter_intel.brief import BriefGenerator
from src.twitter_intel.store import TwitterIntelStore


@pytest.fixture
def store_with_signals(tmp_path):
    s = TwitterIntelStore(db_path=str(tmp_path / "test.db"))
    s.upsert_expert("a")
    s.upsert_expert("b")
    s.insert_tweet("t1", "a", "", 0, 0)
    s.insert_tweet("t2", "b", "", 0, 0)
    s.insert_signal("t1", "BTC", "crypto", "bullish")
    s.insert_signal("t2", "BTC", "crypto", "bullish")
    return s


def _mock_claude(text: str):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


def test_generate_returns_string_with_stats_footer(store_with_signals):
    mock_client = _mock_claude("📊 *Daily Trading Brief*\n\nBTC is hot")
    with patch("src.twitter_intel.brief.Anthropic", return_value=mock_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        gen = BriefGenerator(store_with_signals, min_expert_mentions=1)
        text = gen.generate()
    assert "📡" in text  # stats footer added
    assert "Monitoring" in text


def test_generate_no_signals_returns_placeholder(tmp_path):
    store = TwitterIntelStore(db_path=str(tmp_path / "empty.db"))
    with patch("src.twitter_intel.brief.Anthropic"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        gen = BriefGenerator(store, min_expert_mentions=2)
        text = gen.generate()
    assert "No significant signals" in text


def test_generate_respects_min_expert_mentions(store_with_signals):
    """With min_expert_mentions=3 and only 2 experts, should return placeholder."""
    with patch("src.twitter_intel.brief.Anthropic"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
        gen = BriefGenerator(store_with_signals, min_expert_mentions=3)
        text = gen.generate()
    assert "No significant signals" in text


def test_send_calls_telegram_api(store_with_signals):
    mock_client = _mock_claude("📊 Brief content")
    with patch("src.twitter_intel.brief.Anthropic", return_value=mock_client), \
         patch("src.twitter_intel.brief.requests.post") as mock_post, \
         patch.dict("os.environ", {
             "ANTHROPIC_API_KEY": "test",
             "TELEGRAM_BOT_TOKEN": "tok",
             "TELEGRAM_CHAT_ID": "123",
         }):
        mock_post.return_value.raise_for_status = MagicMock()
        gen = BriefGenerator(store_with_signals, min_expert_mentions=1)
        gen.send()
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "sendMessage" in call_kwargs[0][0]


def test_send_saves_fallback_file_on_telegram_failure(store_with_signals, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock_client = _mock_claude("📊 Brief content")
    with patch("src.twitter_intel.brief.Anthropic", return_value=mock_client), \
         patch("src.twitter_intel.brief.requests.post", side_effect=Exception("down")), \
         patch.dict("os.environ", {
             "ANTHROPIC_API_KEY": "test",
             "TELEGRAM_BOT_TOKEN": "tok",
             "TELEGRAM_CHAT_ID": "123",
         }):
        gen = BriefGenerator(store_with_signals, min_expert_mentions=1)
        gen.send()
    log_files = list((tmp_path / "logs").glob("brief-*.txt"))
    assert len(log_files) == 1
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_twitter_intel/test_brief.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.twitter_intel.brief'`

**Step 3: Implement `src/twitter_intel/brief.py`**

```python
import json
import logging
import os
from datetime import date
from pathlib import Path

import requests
from anthropic import Anthropic

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)

_SYNTHESIS_PROMPT = """\
You are a professional trading analyst. Based on these signals from expert traders on Twitter \
(ranked by number of distinct experts who mentioned each asset), write a concise daily trading brief.

Signals:
{signals_json}

Write a brief with up to 3 entries per section (skip sections with no data):
  🏦 *Stocks to Watch*
  🪙 *Crypto Signals*
  🎯 *Polymarket Attention*

For each entry include: the ticker, expert count, dominant sentiment, and a one-line insight.
Use Telegram Markdown (* bold, _ italic). Start with: 📊 *Daily Trading Brief — {date}*
Return only the formatted message, no extra commentary."""


class BriefGenerator:
    def __init__(
        self,
        store: TwitterIntelStore,
        lookback_hours: int = 24,
        min_expert_mentions: int = 2,
    ):
        self.store = store
        self.lookback_hours = lookback_hours
        self.min_expert_mentions = min_expert_mentions
        self.client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def generate(self) -> str:
        signals = self.store.get_signals_for_brief(self.lookback_hours)
        filtered = [s for s in signals if s["expert_count"] >= self.min_expert_mentions]

        if not filtered:
            text = (
                f"📊 *Daily Trading Brief — {date.today().strftime('%b %d, %Y')}*\n\n"
                f"_No significant signals today "
                f"(need ≥{self.min_expert_mentions} expert mentions per asset)._"
            )
        else:
            msg = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": _SYNTHESIS_PROMPT.format(
                        signals_json=json.dumps(filtered, ensure_ascii=False, indent=2),
                        date=date.today().strftime("%b %d, %Y"),
                    ),
                }],
            )
            text = msg.content[0].text.strip()

        expert_count = self.store.get_expert_count()
        tweet_count = self.store.get_tweet_count_24h()
        text += f"\n\n📡 _Monitoring {expert_count} accounts · {tweet_count} tweets analyzed_"
        return text

    def send(self):
        brief = self.generate()
        try:
            token = os.environ["TELEGRAM_BOT_TOKEN"]
            chat_id = os.environ["TELEGRAM_CHAT_ID"]
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": brief, "parse_mode": "Markdown"},
                timeout=10,
            )
            resp.raise_for_status()
            logger.info("Daily brief sent via Telegram (%d chars)", len(brief))
        except Exception as e:
            logger.error("Telegram send failed: %s — saving to file", e)
            path = Path(f"logs/brief-{date.today()}.txt")
            path.parent.mkdir(exist_ok=True)
            path.write_text(brief)
            logger.info("Brief saved to %s", path)
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_twitter_intel/test_brief.py -v
```
Expected: 5 tests PASSED.

**Step 5: Commit**

```bash
git add src/twitter_intel/brief.py tests/test_twitter_intel/test_brief.py
git commit -m "feat: add brief generator with Telegram delivery"
```

---

## Task 7: Scheduler + Package Init

**Files:**
- Create: `src/twitter_intel/scheduler.py`
- Modify: `src/twitter_intel/__init__.py`

No unit tests for the scheduler wiring itself — it's covered by integration in Task 8.

**Step 1: Implement `src/twitter_intel/scheduler.py`**

```python
import logging

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler

from .brief import BriefGenerator
from .discovery import ExpertDiscovery
from .extractor import SignalExtractor
from .scraper import TwitterScraper
from .store import TwitterIntelStore

logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_components(cfg: dict):
    intel_cfg = cfg.get("twitter_intel", {})
    store = TwitterIntelStore()

    for handle in intel_cfg.get("seed_accounts", []):
        store.upsert_expert(handle, source="seed")

    scraper = TwitterScraper()
    extractor = SignalExtractor(store)
    discovery = ExpertDiscovery(
        store,
        max_accounts=intel_cfg.get("auto_expand", {}).get("max_accounts", 100),
        min_interactions=intel_cfg.get("auto_expand", {}).get("min_interactions", 3),
    )
    brief = BriefGenerator(
        store,
        lookback_hours=intel_cfg.get("lookback_hours", 24),
        min_expert_mentions=intel_cfg.get("min_expert_mentions", 2),
    )
    return store, scraper, extractor, discovery, brief


def scrape_and_extract(store, scraper, extractor, discovery, cfg):
    handles = store.get_active_experts()
    logger.info("Scraping %d expert accounts...", len(handles))

    all_tweets = []
    for handle, tweets in scraper.scrape_all(handles).items():
        for t in tweets:
            store.insert_tweet(t["tweet_id"], handle, t["text"], t["likes"], t["retweets"])
            all_tweets.append({"tweet_id": t["tweet_id"], "text": t["text"]})

    count = extractor.run()
    logger.info("Extracted %d signals", count)

    if cfg.get("twitter_intel", {}).get("auto_expand", {}).get("enabled", True):
        added = discovery.run(all_tweets)
        if added:
            logger.info("Added %d experts via auto-discovery", added)


def run(config_path: str = "config.yaml"):
    cfg = load_config(config_path)
    intel_cfg = cfg.get("twitter_intel", {})
    store, scraper, extractor, discovery, brief = build_components(cfg)

    interval_hours = intel_cfg.get("scrape_interval_hours", 4)
    brief_time = intel_cfg.get("brief_time", "08:00")
    brief_hour, brief_minute = map(int, brief_time.split(":"))

    scheduler = BlockingScheduler()

    scheduler.add_job(
        scrape_and_extract,
        "interval",
        hours=interval_hours,
        args=[store, scraper, extractor, discovery, cfg],
        id="scrape",
    )
    scheduler.add_job(
        brief.send,
        "cron",
        hour=brief_hour,
        minute=brief_minute,
        id="brief",
    )
    scheduler.add_job(
        store.prune_old_tweets,
        "cron",
        hour=2,
        minute=0,
        id="prune",
    )

    logger.info(
        "Twitter Intel started. Brief at %s, scraping every %dh.",
        brief_time,
        interval_hours,
    )
    # Immediate first scrape on startup
    scrape_and_extract(store, scraper, extractor, discovery, cfg)
    scheduler.start()
```

**Step 2: Update `src/twitter_intel/__init__.py`**

```python
from .store import TwitterIntelStore
from .scraper import TwitterScraper
from .extractor import SignalExtractor
from .discovery import ExpertDiscovery
from .brief import BriefGenerator

__all__ = [
    "TwitterIntelStore",
    "TwitterScraper",
    "SignalExtractor",
    "ExpertDiscovery",
    "BriefGenerator",
]
```

**Step 3: Verify all existing tests still pass**

```bash
pytest tests/test_twitter_intel/ -v
```
Expected: all previous tests PASSED, no regressions.

**Step 4: Commit**

```bash
git add src/twitter_intel/scheduler.py src/twitter_intel/__init__.py
git commit -m "feat: add APScheduler wiring for twitter intel"
```

---

## Task 8: Manual Trigger Script

**Files:**
- Create: `scripts/run_intel.py`

**Step 1: Implement `scripts/run_intel.py`**

```python
"""
Manual trigger for Twitter Intel.

Usage:
    python scripts/run_intel.py scrape    # scrape + extract signals now
    python scripts/run_intel.py brief     # generate + send brief now
    python scripts/run_intel.py start     # start the scheduler (blocking)
"""
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
sys.path.insert(0, ".")

from src.twitter_intel import scheduler as sched


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    cfg = sched.load_config()
    store, scraper, extractor, discovery, brief = sched.build_components(cfg)

    if cmd == "scrape":
        sched.scrape_and_extract(store, scraper, extractor, discovery, cfg)
    elif cmd == "brief":
        brief.send()
    elif cmd == "start":
        sched.run()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

**Step 2: Verify the script is importable (dry check)**

```bash
python -c "import scripts.run_intel" 2>&1 || python scripts/run_intel.py 2>&1 | head -5
```
Expected: prints usage text or exits cleanly (no ImportError).

**Step 3: Commit**

```bash
git add scripts/run_intel.py
git commit -m "feat: add manual trigger script for twitter intel"
```

---

## Task 9: Full Test Suite + Smoke Check

**Step 1: Run the full test suite**

```bash
pytest tests/ -v
```
Expected: all tests PASSED with no errors.

**Step 2: Dry-run the brief command (no real scraping)**

Set a dummy env and call the brief command with an empty store to confirm the no-signals path works end-to-end:

```bash
ANTHROPIC_API_KEY=dummy TELEGRAM_BOT_TOKEN=dummy TELEGRAM_CHAT_ID=123 \
  python -c "
import sys; sys.path.insert(0, '.')
from src.twitter_intel.store import TwitterIntelStore
from src.twitter_intel.brief import BriefGenerator
from unittest.mock import patch

store = TwitterIntelStore(db_path=':memory:')
with patch('src.twitter_intel.brief.Anthropic'):
    gen = BriefGenerator(store, min_expert_mentions=2)
    print(gen.generate())
"
```
Expected: prints a message containing "No significant signals today".

**Step 3: Commit**

```bash
git add .
git commit -m "test: confirm full twitter intel test suite passes"
```

---

## Summary

| Task | Files created | Tests |
|------|--------------|-------|
| 1. Scaffold | dirs, config, deps | — |
| 2. Store | `store.py` | 8 |
| 3. Scraper | `scraper.py` | 7 |
| 4. Extractor | `extractor.py` | 6 |
| 5. Discovery | `discovery.py` | 5 |
| 6. Brief | `brief.py` | 5 |
| 7. Scheduler | `scheduler.py`, `__init__.py` | — |
| 8. Script | `scripts/run_intel.py` | — |
| 9. Smoke | — | all pass |

To start the live system after setup:
```bash
python scripts/run_intel.py start
```

To send a one-off brief:
```bash
python scripts/run_intel.py brief
```
