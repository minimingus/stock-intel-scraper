import logging
from playwright.sync_api import sync_playwright, Page

logger = logging.getLogger(__name__)


def _parse_count(text: str) -> int:
    """Parse display counts: '1.2K' -> 1200, '5.6M' -> 5_600_000, '34' -> 34."""
    text = text.strip().replace(",", "")
    if not text:
        return 0
    try:
        if text.upper().endswith("K"):
            return int(float(text[:-1]) * 1_000)
        if text.upper().endswith("M"):
            return int(float(text[:-1]) * 1_000_000)
        return int(float(text))
    except ValueError:
        return 0


def _extract_tweets_from_page(page: Page) -> list:
    tweets = []
    for el in page.locator('[data-testid="tweet"]').all():
        text_el = el.locator('[data-testid="tweetText"]').first
        text = text_el.inner_text() if text_el.count() > 0 else ""
        if not text:
            continue

        tweet_id = ""
        for link in el.locator('a[href*="/status/"]').all():
            href = link.get_attribute("href") or ""
            if "/status/" in href:
                tweet_id = href.split("/status/")[1].split("/")[0].split("?")[0]
                break
        if not tweet_id:
            logger.debug("Could not extract tweet_id for a tweet element, skipping")
            continue

        like_el = el.locator('[data-testid="like"] span').last
        likes_text = like_el.inner_text() if like_el.count() > 0 else "0"
        rt_el = el.locator('[data-testid="retweet"] span').last
        rt_text = rt_el.inner_text() if rt_el.count() > 0 else "0"

        tweets.append({
            "tweet_id": tweet_id,
            "text": text,
            "likes": _parse_count(likes_text),
            "retweets": _parse_count(rt_text),
        })
    return tweets


class TwitterScraper:
    def scrape_handle(self, handle: str) -> list:
        """Scrape recent tweets for a handle. Returns list of tweet dicts."""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                page = context.new_page()
                try:
                    page.goto(
                        f"https://x.com/{handle}",
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                    if page.locator('[data-testid="loginButton"]').count() > 0:
                        logger.warning("Login wall for @%s, skipping", handle)
                        return []
                    page.wait_for_selector('[data-testid="tweet"]', timeout=15_000)
                    return _extract_tweets_from_page(page)
                except Exception as e:
                    logger.warning("Failed to scrape @%s: %s", handle, e)
                    return []
                finally:
                    context.close()
                    browser.close()
        except Exception as e:
            logger.warning("Playwright error for @%s: %s", handle, e)
            return []

    def scrape_all(self, handles: list) -> dict:
        """Scrape multiple handles. Returns {handle: [tweets]}."""
        results = {}
        for handle in handles:
            results[handle] = self.scrape_handle(handle)
            logger.info("Scraped @%s: %d tweets", handle, len(results[handle]))
        return results
