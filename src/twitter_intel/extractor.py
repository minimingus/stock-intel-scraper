import logging
import re

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)

# Common crypto tickers to distinguish from stock tickers
_CRYPTO = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOGE", "MATIC",
    "DOT", "LINK", "UNI", "ATOM", "LTC", "BCH", "XLM", "ALGO", "VET",
    "FIL", "THETA", "TRX", "EOS", "XMR", "AAVE", "COMP", "SNX", "MKR",
    "SHIB", "PEPE", "ARB", "OP", "SUI", "APT", "INJ", "SEI", "TIA",
}

_BULLISH = re.compile(
    r"\b(bull(?:ish)?|long|buy|breakout|moon|pump|surge|rally|rip|go(?:ing)? up|ATH|upside)\b",
    re.IGNORECASE,
)
_BEARISH = re.compile(
    r"\b(bear(?:ish)?|short|sell|dump|crash|drop(?:ping)?|downside|correction|lower)\b",
    re.IGNORECASE,
)


def _sentiment(text: str) -> str:
    bulls = len(_BULLISH.findall(text))
    bears = len(_BEARISH.findall(text))
    if bulls > bears:
        return "bullish"
    if bears > bulls:
        return "bearish"
    return "neutral"


def _extract_tickers(text: str) -> list[dict]:
    """Return list of {ticker, asset_type} from cashtags, hashtag-tickers, and bare crypto names."""
    results = []
    seen = set()

    # Cashtags: $BTC, $NVDA
    for m in re.finditer(r"\$([A-Z]{1,6})", text):
        ticker = m.group(1)
        if ticker in seen:
            continue
        seen.add(ticker)
        asset_type = "crypto" if ticker in _CRYPTO else "stock"
        results.append({"ticker": ticker, "asset_type": asset_type})

    # Hashtag crypto tickers: #BTC, #XRP, #ETH
    for m in re.finditer(r"#([A-Za-z]{1,6})\b", text):
        ticker = m.group(1).upper()
        if ticker in seen or ticker not in _CRYPTO:
            continue
        seen.add(ticker)
        results.append({"ticker": ticker, "asset_type": "crypto"})

    # Bare crypto names without $ (e.g. "Bitcoin", "Ethereum", "Solana")
    crypto_aliases = {
        "BITCOIN": "BTC", "ETHEREUM": "ETH", "SOLANA": "SOL",
        "CARDANO": "ADA", "RIPPLE": "XRP", "DOGECOIN": "DOGE",
    }
    for word, ticker in crypto_aliases.items():
        if re.search(rf"\b{word}\b", text, re.IGNORECASE) and ticker not in seen:
            seen.add(ticker)
            results.append({"ticker": ticker, "asset_type": "crypto"})

    return results


class SignalExtractor:
    def __init__(self, store: TwitterIntelStore):
        self.store = store

    def extract_batch(self, tweets: list) -> int:
        """Extract signals from a batch of tweets. Returns count of signals stored."""
        count = 0
        for tweet in tweets:
            text = tweet.get("text", "")
            tweet_id = tweet["tweet_id"]
            sentiment = _sentiment(text)
            for item in _extract_tickers(text):
                try:
                    self.store.insert_signal(
                        tweet_id=tweet_id,
                        ticker=item["ticker"],
                        asset_type=item["asset_type"],
                        sentiment=sentiment,
                    )
                    count += 1
                except Exception as e:
                    logger.warning("Skipping signal %s: %s", item, e)
        return count

    def run(self) -> int:
        """Extract signals from all unprocessed tweets in the store."""
        return self.extract_batch(self.store.get_new_tweets())
