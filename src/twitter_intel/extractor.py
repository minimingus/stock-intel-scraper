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

# Must mention TA or pump signals — otherwise skip the tweet for stocks
_TA_OR_PUMP = re.compile(
    r"\b(breakout|breakdown|support|resistance|RSI|MACD|EMA|SMA|moving average|"
    r"volume|chart|pattern|wedge|flag|triangle|channel|trend(?:line)?|"
    r"pump|squeeze|gap(?:\s+up)?|momentum|catalyst|runner|scanner|watch(?:list)?|"
    r"penny|small.?cap|micro.?cap|alert|setup|play|trade)\b",
    re.IGNORECASE,
)

_DAY_TRADE = re.compile(
    r"\b(day.?trad|intraday|scalp|today|pre.?market|after.?hours|opening|gap(?:\s+up)?|"
    r"quick|momentum play|alert|runner|scanner|pump|squeeze|catalyst)\b",
    re.IGNORECASE,
)
_SWING = re.compile(
    r"\b(swing|weekly|position|accumulate|hold(?:ing)?|weeks?|months?|"
    r"target|channel|trend|breakout|setup|long.?term|mid.?term)\b",
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


def _trade_type(text: str) -> str:
    day = len(_DAY_TRADE.findall(text))
    swing = len(_SWING.findall(text))
    if day > swing:
        return "day"
    if swing > day:
        return "swing"
    return "day"  # default to day trade when ambiguous


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

            # For stocks: only process tweets with TA or pump signals
            has_ta = bool(_TA_OR_PUMP.search(text))
            sentiment = _sentiment(text)
            trade_type = _trade_type(text)

            for item in _extract_tickers(text):
                # Skip non-TA/pump stock tweets
                if item["asset_type"] == "stock" and not has_ta:
                    continue
                try:
                    self.store.insert_signal(
                        tweet_id=tweet_id,
                        ticker=item["ticker"],
                        asset_type=item["asset_type"],
                        sentiment=sentiment,
                        trade_type=trade_type,
                    )
                    count += 1
                except Exception as e:
                    logger.warning("Skipping signal %s: %s", item, e)
        return count

    def run(self) -> int:
        """Extract signals from all unprocessed tweets in the store."""
        return self.extract_batch(self.store.get_new_tweets())
