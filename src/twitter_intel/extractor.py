import logging
import re

from .store import TwitterIntelStore

logger = logging.getLogger(__name__)

# Common crypto tickers — used only to EXCLUDE them from stock signals
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

# Target price patterns: "target $180", "PT $200", "TP 195", "price target: 210.50"
_TARGET_PRICE = re.compile(
    r"(?:target|pt|tp|take[\s-]?profit|price[\s-]?target)[:\s]+\$?(\d{1,6}(?:\.\d{1,2})?)",
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
    return "swing" if swing > day else "day"


def _extract_target_price(text: str) -> float | None:
    m = _TARGET_PRICE.search(text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _extract_ta_notes(text: str) -> str:
    """Extract up to 2 short TA context snippets from tweet text."""
    notes = []
    for match in _TA_OR_PUMP.finditer(text):
        start = max(0, match.start() - 8)
        end = min(len(text), match.end() + 35)
        snippet = text[start:end].strip().replace("\n", " ")
        notes.append(snippet)
    # Deduplicate by first 20 chars
    seen: set = set()
    unique = []
    for n in notes:
        key = n.lower()[:20]
        if key not in seen:
            seen.add(key)
            unique.append(n)
    return "; ".join(unique[:2])[:120]


def _extract_stock_tickers(text: str) -> list[str]:
    """Return stock cashtags only (no crypto)."""
    seen: set = set()
    results = []
    for m in re.finditer(r"\$([A-Z]{1,6})", text):
        ticker = m.group(1)
        if ticker not in seen and ticker not in _CRYPTO:
            seen.add(ticker)
            results.append(ticker)
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

            if not _TA_OR_PUMP.search(text):
                continue

            sentiment = _sentiment(text)
            trade_type = _trade_type(text)
            target_price = _extract_target_price(text)
            ta_notes = _extract_ta_notes(text)

            for ticker in _extract_stock_tickers(text):
                try:
                    self.store.insert_signal(
                        tweet_id=tweet_id,
                        ticker=ticker,
                        asset_type="stock",
                        sentiment=sentiment,
                        trade_type=trade_type,
                        target_price=target_price,
                        ta_notes=ta_notes,
                    )
                    count += 1
                except Exception as e:
                    logger.warning("Skipping signal %s: %s", ticker, e)
        return count

    def run(self) -> int:
        """Extract signals from all unprocessed tweets in the store."""
        return self.extract_batch(self.store.get_new_tweets())
