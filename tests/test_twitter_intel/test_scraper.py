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


def test_scrape_all_aggregates_results():
    mock_pw = _make_playwright_mock(login_wall=False)
    with patch("src.twitter_intel.scraper.sync_playwright", return_value=mock_pw):
        scraper = TwitterScraper()
        results = scraper.scrape_all(["user1", "user2"])
    assert "user1" in results
    assert "user2" in results
