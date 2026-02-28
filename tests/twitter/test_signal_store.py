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
