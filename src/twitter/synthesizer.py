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
