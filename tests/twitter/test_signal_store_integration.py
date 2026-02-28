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
