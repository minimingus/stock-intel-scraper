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
