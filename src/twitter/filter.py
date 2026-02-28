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
        # Pure retweets (no added commentary) are dropped unconditionally.
        if tweet.is_retweet and not tweet.retweet_text:
            return False
        text_to_check = tweet.retweet_text if tweet.retweet_text else tweet.text
        return self._has_keyword(text_to_check)

    def filter(self, tweets: list[Tweet]) -> list[Tweet]:
        return [t for t in tweets if self._is_relevant(t)]
