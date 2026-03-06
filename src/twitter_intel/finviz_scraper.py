import logging

logger = logging.getLogger(__name__)

_cache: dict = {}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def short_interest(ticker: str) -> float | None:
    """
    Scrape short float % from Finviz using Scrapling.
    Returns float like 0.245 (= 24.5%) or None if unavailable.
    """
    ticker = ticker.upper().strip()
    if ticker in _cache:
        return _cache[ticker]
    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(
            f"https://finviz.com/quote.ashx?t={ticker}",
            headers=_HEADERS,
            timeout=15,
        )
        # Finviz snapshot table: cells alternate label/value
        # Find the cell with text "Short Float" and read the next value cell
        cells = page.css("td.snapshot-td2-cp, td.snapshot-td2")
        for i, cell in enumerate(cells):
            if "Short Float" in (cell.text or ""):
                # The value cell follows immediately
                if i + 1 < len(cells):
                    raw = cells[i + 1].text or ""
                    raw = raw.strip().replace("%", "").replace(",", "")
                    if raw and raw != "-":
                        result = float(raw) / 100
                        _cache[ticker] = result
                        return result
                break
    except Exception as e:
        logger.debug("Finviz scrape failed for %s: %s", ticker, e)
    _cache[ticker] = None
    return None


def clear_cache():
    _cache.clear()
