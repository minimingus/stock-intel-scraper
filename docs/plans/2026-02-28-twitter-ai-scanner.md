# Twitter AI Scanner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a pipeline-based Twitter/X scanner that fetches tweets from curated AI accounts via twikit, filters for relevance, synthesizes with Claude, delivers digests to Telegram every 4h, and writes a signal store for the trading agent to consume.

**Architecture:** `src/twitter/` package with five focused modules (fetcher, filter, synthesizer, signal_store, notifier) orchestrated by `src/scanner.py` using APScheduler. A `data/ai_signals.json` file acts as the integration point between the scanner and the trading agent.

**Tech Stack:** Python 3.12, twikit (unofficial Twitter auth), anthropic SDK, APScheduler, requests (Telegram HTTP), pytest + unittest.mock

---

### Task 1: Project setup — deps, config, gitignore, directory skeleton

**Files:**
- Modify: `requirements.txt`
- Modify: `config.yaml`
- Modify: `.gitignore` (create if missing)
- Create: `data/.gitkeep`
- Create: `src/twitter/__init__.py`
- Create: `tests/twitter/__init__.py`

**Step 1: Add new dependencies to requirements.txt**

```
twikit>=2.3.0
APScheduler>=3.10.0
```

Open `requirements.txt` and append these two lines.

**Step 2: Add twitter block and signal_feed block to config.yaml**

Append to the bottom of `config.yaml`:

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
  lookback_hours: 6
```

**Step 3: Create/update .gitignore**

Add these lines (create `.gitignore` in project root if absent):

```
data/ai_signals.json
data/seen_tweets.json
data/twitter_cookies.json
```

**Step 4: Create directories and empty init files**

```bash
mkdir -p data src/twitter tests/twitter
touch data/.gitkeep src/twitter/__init__.py tests/twitter/__init__.py
```

**Step 5: Add new .env vars to .env.example**

Open `.env.example` and append:

```
TWITTER_USERNAME=your_twitter_username
TWITTER_PASSWORD=your_twitter_password
TWITTER_EMAIL=your_twitter_email
```

**Step 6: Install new deps**

```bash
pip install twikit apscheduler
```

Expected: both packages install without errors.

**Step 7: Commit**

```bash
git add requirements.txt config.yaml .gitignore data/.gitkeep src/twitter/__init__.py tests/twitter/__init__.py
git commit -m "chore: add twitter scanner deps, config, and skeleton dirs"
```

---

### Task 2: SignalStore — persist and query signals

**Files:**
- Create: `src/twitter/signal_store.py`
- Create: `tests/twitter/test_signal_store.py`

**Step 1: Write the failing tests**

Create `tests/twitter/test_signal_store.py`:

```python
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from src.twitter.signal_store import SignalStore


def test_append_signal_persists(tmp_path):
    store = SignalStore(tmp_path / "signals.json", tmp_path / "seen.json")
    sig = store.append_signal("new_release", "Anthropic released Claude 4", ["https://x.com/1"], 0.9)
    assert sig["topic"] == "new_release"
    assert sig["summary"] == "Anthropic released Claude 4"
    loaded = store._load()
    assert len(loaded) == 1
    assert loaded[0]["id"] == sig["id"]


def test_get_signals_since_filters_by_time(tmp_path):
    store = SignalStore(tmp_path / "signals.json", tmp_path / "seen.json")
    store.append_signal("research", "New paper", [], 0.5)
    old = {
        "id": "old-1",
        "timestamp": (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat(),
        "topic": "old", "summary": "old", "sources": [], "relevance_score": 0.1,
    }
    signals = store._load()
    signals.append(old)
    store._save(signals)

    recent = store.get_signals_since(hours=6)
    assert all(s["topic"] != "old" for s in recent)


def test_prune_old_removes_beyond_retention(tmp_path):
    store = SignalStore(tmp_path / "signals.json", tmp_path / "seen.json")
    store.append_signal("new_release", "Recent", [], 0.8)
    old = {
        "id": "old-1",
        "timestamp": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
        "topic": "old", "summary": "old", "sources": [], "relevance_score": 0.1,
    }
    signals = store._load()
    signals.append(old)
    store._save(signals)

    removed = store.prune_old(days=7)
    assert removed == 1
    assert len(store._load()) == 1


def test_is_seen_and_mark_seen(tmp_path):
    store = SignalStore(tmp_path / "signals.json", tmp_path / "seen.json")
    assert not store.is_seen("tweet_123")
    store.mark_seen(["tweet_123", "tweet_456"])
    assert store.is_seen("tweet_123")
    assert store.is_seen("tweet_456")
    assert not store.is_seen("tweet_789")


def test_get_recent_signals_context_formats_as_string(tmp_path):
    store = SignalStore(tmp_path / "signals.json", tmp_path / "seen.json")
    store.append_signal("new_release", "Claude 4 dropped.", ["https://x.com/1"], 0.9)
    ctx = store.get_recent_signals_context(hours=6)
    assert "new_release" in ctx
    assert "Claude 4 dropped." in ctx
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/twitter/test_signal_store.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'src.twitter.signal_store'`

**Step 3: Implement `src/twitter/signal_store.py`**

```python
import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_PATH = Path("data/ai_signals.json")
SEEN_PATH = Path("data/seen_tweets.json")


class SignalStore:
    def __init__(self, signals_path: Path = DATA_PATH, seen_path: Path = SEEN_PATH):
        self._signals_path = signals_path
        self._seen_path = seen_path
        self._signals_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict]:
        if not self._signals_path.exists():
            return []
        return json.loads(self._signals_path.read_text())

    def _save(self, signals: list[dict]) -> None:
        self._signals_path.write_text(json.dumps(signals, indent=2))

    def append_signal(
        self, topic: str, summary: str, sources: list[str], relevance_score: float
    ) -> dict:
        signal = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "topic": topic,
            "summary": summary,
            "sources": sources,
            "relevance_score": relevance_score,
        }
        signals = self._load()
        signals.append(signal)
        self._save(signals)
        return signal

    def get_signals_since(self, hours: int) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [
            s for s in self._load()
            if datetime.fromisoformat(s["timestamp"]) > cutoff
        ]

    def prune_old(self, days: int = 7) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        signals = self._load()
        kept = [s for s in signals if datetime.fromisoformat(s["timestamp"]) > cutoff]
        removed = len(signals) - len(kept)
        self._save(kept)
        return removed

    def is_seen(self, tweet_id: str) -> bool:
        if not self._seen_path.exists():
            return False
        seen = json.loads(self._seen_path.read_text())
        return tweet_id in seen

    def mark_seen(self, tweet_ids: list[str]) -> None:
        seen: set[str] = set()
        if self._seen_path.exists():
            seen = set(json.loads(self._seen_path.read_text()))
        seen.update(tweet_ids)
        # cap at 10k to avoid unbounded growth
        self._seen_path.write_text(json.dumps(list(seen)[-10000:]))

    def get_recent_signals_context(self, hours: int = 6) -> str:
        """Return a formatted string of recent signals for injection into AI prompts."""
        signals = self.get_signals_since(hours=hours)
        if not signals:
            return ""
        lines = [f"Recent AI news context (last {hours}h):"]
        for s in signals:
            lines.append(f"- {s['topic']}: {s['summary']}")
        return "\n".join(lines)
```

**Step 4: Run tests and verify they pass**

```bash
pytest tests/twitter/test_signal_store.py -v
```

Expected: `5 passed`

**Step 5: Commit**

```bash
git add src/twitter/signal_store.py tests/twitter/test_signal_store.py
git commit -m "feat: add SignalStore for persisting and querying AI signals"
```

---

### Task 3: RelevanceFilter — keyword + engagement filtering

**Files:**
- Create: `src/twitter/filter.py`
- Create: `tests/twitter/test_filter.py`

**Step 1: Write the failing tests**

Create `tests/twitter/test_filter.py`:

```python
import pytest
from src.twitter.filter import RelevanceFilter, Tweet


def _tweet(id="1", text="", is_retweet=False, like_count=10, retweet_text=None):
    return Tweet(
        id=id, author="test", text=text,
        url=f"https://x.com/{id}", like_count=like_count,
        is_retweet=is_retweet, retweet_text=retweet_text,
    )


def test_passes_original_tweet_with_keyword():
    f = RelevanceFilter()
    tweet = _tweet(text="Claude 4 just launched with new reasoning!")
    assert f.filter([tweet]) == [tweet]


def test_drops_pure_retweet_with_no_commentary():
    f = RelevanceFilter()
    tweet = _tweet(
        text="RT @AnthropicAI: Claude 4 launched",
        is_retweet=True, retweet_text=None,
    )
    assert f.filter([tweet]) == []


def test_passes_retweet_with_commentary_and_keyword():
    f = RelevanceFilter()
    tweet = _tweet(
        text="RT @user: some text", is_retweet=True,
        retweet_text="This new model release changes everything!", like_count=0,
    )
    assert f.filter([tweet]) == [tweet]


def test_drops_retweet_below_engagement_threshold():
    f = RelevanceFilter(min_engagement=5)
    tweet = _tweet(
        text="RT @user: Claude launch", is_retweet=True,
        retweet_text=None, like_count=2,
    )
    assert f.filter([tweet]) == []


def test_drops_original_tweet_without_keyword():
    f = RelevanceFilter()
    tweet = _tweet(text="Just had a great coffee this morning!")
    assert f.filter([tweet]) == []


def test_keyword_match_is_case_insensitive():
    f = RelevanceFilter()
    tweet = _tweet(text="CLAUDE just dropped a new RELEASE!")
    assert f.filter([tweet]) == [tweet]


def test_empty_input_returns_empty():
    f = RelevanceFilter()
    assert f.filter([]) == []
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/twitter/test_filter.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'src.twitter.filter'`

**Step 3: Implement `src/twitter/filter.py`**

```python
from dataclasses import dataclass

DEFAULT_KEYWORDS = [
    "release", "launch", "new model", "api", "open source", "benchmark",
    "gpt", "claude", "gemini", "llama", "agent", "coding", "cursor", "copilot",
    "weights", "fine-tun", "training", "inference", "context window",
    "multimodal", "reasoning", "grok", "o1", "o3",
]


@dataclass
class Tweet:
    id: str
    author: str
    text: str
    url: str
    like_count: int
    is_retweet: bool
    retweet_text: str | None = None


class RelevanceFilter:
    def __init__(self, min_engagement: int = 5, keywords: list[str] | None = None):
        self._min_engagement = min_engagement
        self._keywords = [k.lower() for k in (keywords or DEFAULT_KEYWORDS)]

    def _has_keyword(self, text: str) -> bool:
        lower = text.lower()
        return any(kw in lower for kw in self._keywords)

    def _is_relevant(self, tweet: Tweet) -> bool:
        if tweet.is_retweet and not tweet.retweet_text:
            return False
        if tweet.is_retweet and tweet.like_count < self._min_engagement:
            return False
        text_to_check = tweet.retweet_text if tweet.retweet_text else tweet.text
        return self._has_keyword(text_to_check)

    def filter(self, tweets: list[Tweet]) -> list[Tweet]:
        return [t for t in tweets if self._is_relevant(t)]
```

**Step 4: Run tests and verify they pass**

```bash
pytest tests/twitter/test_filter.py -v
```

Expected: `7 passed`

**Step 5: Commit**

```bash
git add src/twitter/filter.py tests/twitter/test_filter.py
git commit -m "feat: add RelevanceFilter for tweet keyword and engagement filtering"
```

---

### Task 4: TweetFetcher — twikit-based tweet fetching with dedup

**Files:**
- Create: `src/twitter/fetcher.py`
- Create: `tests/twitter/test_fetcher.py`

**Step 1: Write the failing tests**

Create `tests/twitter/test_fetcher.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
from src.twitter.fetcher import TweetFetcher
from src.twitter.signal_store import SignalStore


def _raw_tweet(id, text, likes=10, is_retweet=False, age_minutes=30):
    t = MagicMock()
    t.id = id
    t.full_text = text
    t.favorite_count = likes
    t.retweeted_tweet = MagicMock() if is_retweet else None
    t.created_at_datetime = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    return t


def test_fetch_returns_new_tweets_and_deduplicates(tmp_path):
    with patch("src.twitter.fetcher.Client") as MockClient:
        inst = MockClient.return_value
        inst.load_cookies = MagicMock()
        mock_user = AsyncMock()
        mock_user.get_tweets = AsyncMock(return_value=[
            _raw_tweet("t1", "Claude 4 release is here!"),
            _raw_tweet("t2", "New Cursor update dropped"),
        ])
        inst.get_user_by_screen_name = AsyncMock(return_value=mock_user)

        cookies = tmp_path / "cookies.json"
        cookies.write_text("[]")
        store = SignalStore(tmp_path / "signals.json", tmp_path / "seen.json")

        fetcher = TweetFetcher("user", "pass", "e@x.com", cookies_path=cookies)
        tweets = fetcher.fetch(["AnthropicAI"], since_hours=4, store=store)
        assert len(tweets) == 2

        # Second call: all seen, returns empty
        tweets2 = fetcher.fetch(["AnthropicAI"], since_hours=4, store=store)
        assert len(tweets2) == 0


def test_fetch_skips_tweets_older_than_window(tmp_path):
    with patch("src.twitter.fetcher.Client") as MockClient:
        inst = MockClient.return_value
        inst.load_cookies = MagicMock()
        old_tweet = _raw_tweet("t_old", "An old GPT tweet", age_minutes=300)
        mock_user = AsyncMock()
        mock_user.get_tweets = AsyncMock(return_value=[old_tweet])
        inst.get_user_by_screen_name = AsyncMock(return_value=mock_user)

        cookies = tmp_path / "cookies.json"
        cookies.write_text("[]")

        fetcher = TweetFetcher("user", "pass", "e@x.com", cookies_path=cookies)
        tweets = fetcher.fetch(["OpenAI"], since_hours=4)
        assert tweets == []


def test_fetch_handles_account_error_gracefully(tmp_path):
    with patch("src.twitter.fetcher.Client") as MockClient:
        inst = MockClient.return_value
        inst.load_cookies = MagicMock()
        inst.get_user_by_screen_name = AsyncMock(side_effect=Exception("User not found"))

        cookies = tmp_path / "cookies.json"
        cookies.write_text("[]")

        fetcher = TweetFetcher("user", "pass", "e@x.com", cookies_path=cookies)
        tweets = fetcher.fetch(["ghost_account"], since_hours=4)
        assert tweets == []
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/twitter/test_fetcher.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'src.twitter.fetcher'`

**Step 3: Implement `src/twitter/fetcher.py`**

```python
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

from twikit import Client

from src.twitter.filter import Tweet
from src.twitter.signal_store import SignalStore

COOKIES_PATH = Path("data/twitter_cookies.json")


class TweetFetcher:
    def __init__(
        self,
        username: str,
        password: str,
        email: str,
        cookies_path: Path = COOKIES_PATH,
    ):
        self._username = username
        self._password = password
        self._email = email
        self._cookies_path = cookies_path
        self._client = Client("en-US")

    async def _ensure_authenticated(self) -> None:
        if self._cookies_path.exists():
            self._client.load_cookies(str(self._cookies_path))
        else:
            await self._client.login(
                auth_info_1=self._username,
                auth_info_2=self._email,
                password=self._password,
            )
            self._cookies_path.parent.mkdir(parents=True, exist_ok=True)
            self._client.save_cookies(str(self._cookies_path))

    async def _fetch_user_tweets(
        self, screen_name: str, since_hours: int
    ) -> list[Tweet]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        try:
            user = await self._client.get_user_by_screen_name(screen_name)
            raw_tweets = await user.get_tweets("Tweets", count=40)
        except Exception:
            return []

        tweets = []
        for t in raw_tweets:
            if t.created_at_datetime and t.created_at_datetime < cutoff:
                continue
            is_retweet = t.retweeted_tweet is not None
            retweet_text = None
            if is_retweet and t.full_text and not t.full_text.startswith("RT "):
                retweet_text = t.full_text
            tweets.append(
                Tweet(
                    id=t.id,
                    author=screen_name,
                    text=t.full_text or "",
                    url=f"https://x.com/{screen_name}/status/{t.id}",
                    like_count=t.favorite_count or 0,
                    is_retweet=is_retweet,
                    retweet_text=retweet_text,
                )
            )
        return tweets

    async def _fetch_all(
        self, accounts: list[str], since_hours: int
    ) -> list[Tweet]:
        await self._ensure_authenticated()
        results: list[Tweet] = []
        for account in accounts:
            results.extend(await self._fetch_user_tweets(account, since_hours))
        return results

    def fetch(
        self,
        accounts: list[str],
        since_hours: int,
        store: SignalStore | None = None,
    ) -> list[Tweet]:
        """Synchronous wrapper. Deduplicates against store if provided."""
        tweets = asyncio.run(self._fetch_all(accounts, since_hours))
        if store is None:
            return tweets
        new_tweets = [t for t in tweets if not store.is_seen(t.id)]
        store.mark_seen([t.id for t in new_tweets])
        return new_tweets
```

**Step 4: Run tests and verify they pass**

```bash
pytest tests/twitter/test_fetcher.py -v
```

Expected: `3 passed`

**Step 5: Commit**

```bash
git add src/twitter/fetcher.py tests/twitter/test_fetcher.py
git commit -m "feat: add TweetFetcher with twikit auth and deduplication"
```

---

### Task 5: Synthesizer — Claude-powered narrative synthesis

**Files:**
- Create: `src/twitter/synthesizer.py`
- Create: `tests/twitter/test_synthesizer.py`

**Step 1: Write the failing tests**

Create `tests/twitter/test_synthesizer.py`:

```python
import pytest
from unittest.mock import MagicMock
from src.twitter.synthesizer import Synthesizer
from src.twitter.filter import Tweet


def _mock_client(response_json: str):
    client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=response_json)]
    client.messages.create.return_value = msg
    return client


def _tweet(id="1", author="AnthropicAI", text="Claude 4 is here!"):
    return Tweet(id=id, author=author, text=text, url=f"https://x.com/{id}",
                 like_count=500, is_retweet=False)


def test_synthesize_returns_structured_signals():
    resp = '[{"topic": "new_release", "summary": "Anthropic released Claude 4.", "tweets": [{"author": "AnthropicAI", "text": "Claude 4 is here!", "url": "https://x.com/1"}]}]'
    synth = Synthesizer(client=_mock_client(resp))
    result = synth.synthesize([_tweet()])
    assert len(result) == 1
    assert result[0]["topic"] == "new_release"
    assert "Claude 4" in result[0]["summary"]


def test_synthesize_returns_empty_list_for_no_tweets():
    synth = Synthesizer(client=_mock_client("[]"))
    result = synth.synthesize([])
    assert result == []


def test_synthesize_handles_json_with_preamble():
    prefixed = 'Here is the result:\n[{"topic": "research", "summary": "New paper.", "tweets": []}]'
    synth = Synthesizer(client=_mock_client(prefixed))
    result = synth.synthesize([_tweet(text="New reasoning paper published")])
    assert len(result) == 1
    assert result[0]["topic"] == "research"


def test_synthesize_returns_empty_on_unparseable_response():
    synth = Synthesizer(client=_mock_client("I cannot summarize this."))
    result = synth.synthesize([_tweet()])
    assert result == []
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/twitter/test_synthesizer.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'src.twitter.synthesizer'`

**Step 3: Implement `src/twitter/synthesizer.py`**

```python
import json

from anthropic import Anthropic

from src.twitter.filter import Tweet

SYNTHESIS_PROMPT = """\
You are an AI news analyst. Below is a batch of tweets from top AI contributors.

Your task:
1. Group the tweets into topic buckets: new_release, research, devtools, tools, community
2. For each non-empty bucket write ONE concise factual narrative paragraph (3-5 sentences). No hype.
3. Return a JSON array. Each element: {{"topic": "<bucket>", "summary": "<paragraph>", "tweets": [{{"author": "<handle>", "text": "<tweet>", "url": "<url>"}}]}}

If nothing meaningful, return [].

Tweets:
{tweets_block}

Return only valid JSON. No markdown fences."""


class Synthesizer:
    def __init__(self, client: Anthropic | None = None):
        self._client = client or Anthropic()

    def synthesize(self, tweets: list[Tweet]) -> list[dict]:
        if not tweets:
            return []
        tweets_block = "\n".join(
            f"@{t.author}: {t.text} ({t.url})" for t in tweets
        )
        response = self._client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": SYNTHESIS_PROMPT.format(tweets_block=tweets_block)}],
        )
        raw = response.content[0].text.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("["), raw.rfind("]") + 1
            if start != -1 and end > start:
                try:
                    return json.loads(raw[start:end])
                except json.JSONDecodeError:
                    pass
            return []
```

**Step 4: Run tests and verify they pass**

```bash
pytest tests/twitter/test_synthesizer.py -v
```

Expected: `4 passed`

**Step 5: Commit**

```bash
git add src/twitter/synthesizer.py tests/twitter/test_synthesizer.py
git commit -m "feat: add Synthesizer using Claude to group tweets into topic signals"
```

---

### Task 6: TelegramNotifier — format and send digests

**Files:**
- Create: `src/twitter/notifier.py`
- Create: `tests/twitter/test_notifier.py`

**Step 1: Write the failing tests**

Create `tests/twitter/test_notifier.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from src.twitter.notifier import TelegramNotifier


def _notifier():
    return TelegramNotifier(bot_token="test_token", chat_id="12345")


def test_send_digest_posts_to_telegram():
    notifier = _notifier()
    signals = [
        {"topic": "new_release", "summary": "Anthropic launched Claude 4.",
         "tweets": [{"author": "AnthropicAI", "text": "", "url": ""}]},
    ]
    start = datetime(2026, 2, 28, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 28, 14, 0, tzinfo=timezone.utc)

    with patch("src.twitter.notifier.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier.send_digest(signals, start, end)
        mock_post.assert_called_once()
        body = mock_post.call_args[1]["json"]
        assert "AI Pulse" in body["text"]
        assert "New Releases" in body["text"]
        assert "Claude 4" in body["text"]
        assert "@AnthropicAI" in body["text"]


def test_send_digest_skips_when_no_signals():
    notifier = _notifier()
    with patch("src.twitter.notifier.requests.post") as mock_post:
        notifier.send_digest([], datetime.now(), datetime.now())
        mock_post.assert_not_called()


def test_send_daily_brief_includes_header_and_narrative():
    notifier = _notifier()
    with patch("src.twitter.notifier.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier.send_daily_brief("Today was huge for AI.", datetime(2026, 2, 28))
        body = mock_post.call_args[1]["json"]
        assert "Daily AI Brief" in body["text"]
        assert "Today was huge for AI." in body["text"]
        assert "February 28, 2026" in body["text"]
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/twitter/test_notifier.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'src.twitter.notifier'`

**Step 3: Implement `src/twitter/notifier.py`**

```python
import os
from datetime import datetime

import requests

TOPIC_EMOJIS = {
    "new_release": "📦",
    "research": "🔬",
    "devtools": "🛠",
    "tools": "🔧",
    "community": "💬",
}
TOPIC_LABELS = {
    "new_release": "New Releases",
    "research": "Research",
    "devtools": "Dev Tools",
    "tools": "Tools & Products",
    "community": "Community",
}


class TelegramNotifier:
    def __init__(self, bot_token: str | None = None, chat_id: str | None = None):
        self._token = bot_token or os.environ["TELEGRAM_BOT_TOKEN"]
        self._chat_id = chat_id or os.environ["TELEGRAM_CHAT_ID"]

    def _send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        requests.post(
            url,
            json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )

    def send_digest(
        self, signals: list[dict], window_start: datetime, window_end: datetime
    ) -> None:
        if not signals:
            return
        start_str = window_start.strftime("%H:%M")
        end_str = window_end.strftime("%H:%M")
        lines = [f"<b>🤖 AI Pulse — {start_str}–{end_str} UTC</b>\n"]
        for sig in signals:
            emoji = TOPIC_EMOJIS.get(sig["topic"], "•")
            label = TOPIC_LABELS.get(sig["topic"], sig["topic"].replace("_", " ").title())
            lines.append(f"<b>{emoji} {label}</b>")
            lines.append(sig["summary"])
            lines.append("")
        sources = sorted({f"@{tw['author']}" for sig in signals for tw in sig.get("tweets", [])})
        if sources:
            lines.append(f"<i>Sources: {', '.join(sources)}</i>")
        self._send("\n".join(lines))

    def send_daily_brief(self, synthesis: str, date: datetime) -> None:
        date_str = date.strftime("%B %d, %Y")
        self._send(f"<b>📰 Daily AI Brief — {date_str}</b>\n\n{synthesis}")
```

**Step 4: Run tests and verify they pass**

```bash
pytest tests/twitter/test_notifier.py -v
```

Expected: `3 passed`

**Step 5: Commit**

```bash
git add src/twitter/notifier.py tests/twitter/test_notifier.py
git commit -m "feat: add TelegramNotifier for 4h digests and daily brief"
```

---

### Task 7: Scanner — APScheduler orchestration entry point

**Files:**
- Create: `src/scanner.py`
- Create: `scripts/run_scanner.sh`

No unit tests for the scheduler itself (it's glue code). We validate it runs without import errors.

**Step 1: Implement `src/scanner.py`**

```python
import logging
import os
from datetime import datetime, timezone, timedelta

import yaml
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
from anthropic import Anthropic

from src.twitter.fetcher import TweetFetcher
from src.twitter.filter import RelevanceFilter
from src.twitter.synthesizer import Synthesizer
from src.twitter.signal_store import SignalStore
from src.twitter.notifier import TelegramNotifier

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _load_config() -> dict:
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def scan_cycle() -> None:
    cfg = _load_config()
    tw = cfg.get("twitter", {})

    store = SignalStore()
    fetcher = TweetFetcher(
        username=os.environ["TWITTER_USERNAME"],
        password=os.environ["TWITTER_PASSWORD"],
        email=os.environ["TWITTER_EMAIL"],
    )
    filt = RelevanceFilter(
        min_engagement=tw.get("min_engagement", 5),
        keywords=tw.get("keywords_boost"),
    )
    synth = Synthesizer()
    notifier = TelegramNotifier()

    accounts = tw.get("accounts", [])
    since_hours = tw.get("scan_interval_hours", 4)
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(hours=since_hours)

    log.info("Scan cycle: %d accounts, window=%dh", len(accounts), since_hours)
    tweets = fetcher.fetch(accounts, since_hours=since_hours, store=store)
    log.info("Fetched %d new tweets", len(tweets))

    filtered = filt.filter(tweets)
    log.info("Filtered to %d relevant tweets", len(filtered))

    signals = synth.synthesize(filtered)
    log.info("Synthesized %d topic signals", len(signals))

    for sig in signals:
        store.append_signal(
            topic=sig["topic"],
            summary=sig["summary"],
            sources=[tw_["url"] for tw_ in sig.get("tweets", [])],
            relevance_score=1.0,
        )

    store.prune_old(days=7)
    notifier.send_digest(signals, window_start, window_end)


def daily_brief() -> None:
    cfg = _load_config()
    lookback = cfg.get("signal_feed", {}).get("lookback_hours", 24)

    store = SignalStore()
    notifier = TelegramNotifier()
    signals = store.get_signals_since(hours=lookback)

    if not signals:
        log.info("No signals in last %dh — skipping daily brief", lookback)
        return

    summary_text = "\n".join(f"- {s['topic']}: {s['summary']}" for s in signals)
    client = Anthropic()
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": (
                "Write a concise 'what mattered today in AI' narrative "
                "(4-6 sentences) based on these signals:\n" + summary_text
            ),
        }],
    )
    narrative = response.content[0].text.strip()
    notifier.send_daily_brief(narrative, datetime.now(timezone.utc))


def main() -> None:
    cfg = _load_config()
    tw = cfg.get("twitter", {})
    interval_hours = tw.get("scan_interval_hours", 4)
    brief_hour = tw.get("daily_brief_hour_utc", 9)

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(scan_cycle, "interval", hours=interval_hours, id="scan")
    scheduler.add_job(daily_brief, "cron", hour=brief_hour, id="daily_brief")
    log.info(
        "Scanner starting: every %dh + daily brief at %02d:00 UTC",
        interval_hours, brief_hour,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
```

**Step 2: Verify scanner imports cleanly**

```bash
python -c "from src.scanner import scan_cycle, daily_brief, main; print('OK')"
```

Expected: `OK`

**Step 3: Create `scripts/run_scanner.sh`**

```bash
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
source .env 2>/dev/null || true
exec python -m src.scanner
```

Make it executable:

```bash
chmod +x scripts/run_scanner.sh
```

**Step 4: Commit**

```bash
git add src/scanner.py scripts/run_scanner.sh
git commit -m "feat: add Scanner entry point with APScheduler (4h scan + 9am daily brief)"
```

---

### Task 8: Trader integration — expose signal context for AI reasoning

The trading agent needs to be able to call `get_recent_signals_context()` before its Claude reasoning prompt. Since `src/polymarket.py` is a pure CLOB client (no reasoning yet), we wire the integration point now so the future AI reasoning skill can use it with one import.

**Files:**
- Create: `tests/twitter/test_signal_store_integration.py`
- Verify: `src/twitter/signal_store.py` (already has `get_recent_signals_context` — just test it end-to-end)

**Step 1: Write integration test**

Create `tests/twitter/test_signal_store_integration.py`:

```python
from pathlib import Path
from src.twitter.signal_store import SignalStore


def test_signal_context_injected_into_prompt_string(tmp_path):
    store = SignalStore(tmp_path / "signals.json", tmp_path / "seen.json")
    store.append_signal("new_release", "Anthropic released Claude 4.", ["https://x.com/1"], 0.9)
    store.append_signal("devtools", "Cursor 2.0 ships with agent mode.", ["https://x.com/2"], 0.8)

    ctx = store.get_recent_signals_context(hours=6)

    # Simulate how the reasoning skill will use it
    base_prompt = "Analyze these Polymarket markets and decide where to bet."
    full_prompt = base_prompt + "\n\n" + ctx if ctx else base_prompt

    assert "new_release" in full_prompt
    assert "Claude 4" in full_prompt
    assert "Cursor 2.0" in full_prompt
    assert "Recent AI news context" in full_prompt


def test_signal_context_empty_when_no_recent_signals(tmp_path):
    store = SignalStore(tmp_path / "signals.json", tmp_path / "seen.json")
    ctx = store.get_recent_signals_context(hours=6)
    assert ctx == ""
```

**Step 2: Run integration test**

```bash
pytest tests/twitter/test_signal_store_integration.py -v
```

Expected: `2 passed` (these pass immediately since `get_recent_signals_context` was already implemented in Task 2)

**Step 3: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: All tests pass. Note the polymarket tests require the `POLYGON_PRIVATE_KEY` env var — the test file sets it via `os.environ.setdefault`.

**Step 4: Commit**

```bash
git add tests/twitter/test_signal_store_integration.py
git commit -m "test: add signal context integration test for trader prompt injection"
```

---

### Task 9: Final wiring check and smoke test

**Step 1: Verify full import tree**

```bash
python -c "
from src.twitter.signal_store import SignalStore
from src.twitter.filter import RelevanceFilter, Tweet
from src.twitter.fetcher import TweetFetcher
from src.twitter.synthesizer import Synthesizer
from src.twitter.notifier import TelegramNotifier
from src.scanner import scan_cycle, daily_brief, main
print('All imports OK')
"
```

Expected: `All imports OK`

**Step 2: Run all tests**

```bash
pytest tests/ -v --tb=short
```

Expected: All green. Count should be 5 (polymarket) + 5 (signal_store) + 7 (filter) + 3 (fetcher) + 4 (synthesizer) + 3 (notifier) + 2 (integration) = **29 tests passing**.

**Step 3: Verify config has all required keys**

```bash
python -c "
import yaml
cfg = yaml.safe_load(open('config.yaml'))
assert 'twitter' in cfg, 'missing twitter block'
assert 'accounts' in cfg['twitter']
assert len(cfg['twitter']['accounts']) > 0
assert 'signal_feed' in cfg
print('Config OK — accounts:', len(cfg['twitter']['accounts']))
"
```

Expected: `Config OK — accounts: 27`

**Step 4: Final commit**

```bash
git add .
git commit -m "feat: complete Twitter AI scanner pipeline with trader signal integration"
```

---

## Running the Scanner

```bash
# Copy secrets to .env
cp .env.example .env
# Fill in TWITTER_USERNAME, TWITTER_PASSWORD, TWITTER_EMAIL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ANTHROPIC_API_KEY

# First run (will authenticate and save cookies to data/twitter_cookies.json)
./scripts/run_scanner.sh

# Or run a one-off scan cycle for testing:
python -c "from src.scanner import scan_cycle; scan_cycle()"
```

On first run, twikit will perform a real login. Subsequent runs load `data/twitter_cookies.json` and skip the login step. If cookies expire, delete the file and re-run.
