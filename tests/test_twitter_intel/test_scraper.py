from unittest.mock import MagicMock, patch
import pytest
from src.twitter_intel.scraper import TwitterScraper, _parse_count


# --- Unit tests for _parse_count helper ---

def test_parse_count_plain_integer():
    assert _parse_count("34") == 34

def test_parse_count_k_suffix():
    assert _parse_count("1.2K") == 1200

def test_parse_count_m_suffix():
    assert _parse_count("5.6M") == 5_600_000

def test_parse_count_empty_string():
    assert _parse_count("") == 0

def test_parse_count_with_comma():
    assert _parse_count("1,234") == 1234


# --- Behavioural tests for TwitterScraper ---

def _make_playwright_mock(login_wall: bool = False):
    """Build a mock sync_playwright context manager."""
    mock_page = MagicMock()
    login_locator = MagicMock()
    login_locator.count.return_value = 1 if login_wall else 0

    tweet_locator = MagicMock()
    tweet_locator.all.return_value = []

    def locator_side_effect(selector):
        if "loginButton" in selector:
            return login_locator
        return tweet_locator

    mock_page.locator.side_effect = locator_side_effect

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_p = MagicMock()
    mock_p.chromium.launch.return_value = mock_browser

    mock_pw = MagicMock()
    mock_pw.__enter__ = MagicMock(return_value=mock_p)
    mock_pw.__exit__ = MagicMock(return_value=False)
    return mock_pw


def test_scrape_handle_returns_empty_on_login_wall():
    mock_pw = _make_playwright_mock(login_wall=True)
    with patch("src.twitter_intel.scraper.sync_playwright", return_value=mock_pw):
        scraper = TwitterScraper()
        result = scraper.scrape_handle("testuser")
    assert result == []


def test_scrape_handle_returns_empty_on_exception():
    with patch("src.twitter_intel.scraper.sync_playwright", side_effect=Exception("crash")):
        scraper = TwitterScraper()
        result = scraper.scrape_handle("testuser")
    assert result == []


def test_extract_tweets_from_page_returns_tweet_dict():
    """Verify _extract_tweets_from_page extracts a well-formed tweet dict."""
    from src.twitter_intel.scraper import _extract_tweets_from_page

    # Build a minimal mock element tree for one tweet
    mock_text_el = MagicMock()
    mock_text_el.count.return_value = 1
    mock_text_el.inner_text.return_value = "BTC is going to 100k"

    mock_link = MagicMock()
    mock_link.get_attribute.return_value = "/trader/status/123456789/photo/1"

    mock_like_el = MagicMock()
    mock_like_el.count.return_value = 1
    mock_like_el.inner_text.return_value = "1.2K"

    mock_rt_el = MagicMock()
    mock_rt_el.count.return_value = 1
    mock_rt_el.inner_text.return_value = "42"

    def tweet_el_locator(selector):
        if "tweetText" in selector:
            return mock_text_el
        if "/status/" in selector:
            links = MagicMock()
            links.all.return_value = [mock_link]
            return links
        if 'data-testid="like"' in selector:
            return mock_like_el
        if 'data-testid="retweet"' in selector:
            return mock_rt_el
        return MagicMock()

    mock_tweet_el = MagicMock()
    mock_tweet_el.locator.side_effect = tweet_el_locator

    mock_page = MagicMock()
    outer_locator = MagicMock()
    outer_locator.all.return_value = [mock_tweet_el]
    mock_page.locator.return_value = outer_locator

    result = _extract_tweets_from_page(mock_page)

    assert len(result) == 1
    assert result[0]["tweet_id"] == "123456789"
    assert result[0]["text"] == "BTC is going to 100k"
    assert result[0]["likes"] == 1200
    assert result[0]["retweets"] == 42


def test_scrape_all_aggregates_results():
    mock_pw = _make_playwright_mock(login_wall=False)
    with patch("src.twitter_intel.scraper.sync_playwright", return_value=mock_pw):
        scraper = TwitterScraper()
        results = scraper.scrape_all(["user1", "user2"])
    assert "user1" in results
    assert "user2" in results
    assert isinstance(results["user1"], list)
    assert isinstance(results["user2"], list)
