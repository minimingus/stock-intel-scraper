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

    def extract_batch(self, tweets: list) -> int:
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
