import pytest
from src.twitter.filter import RelevanceFilter, Tweet


def _tweet(id="1", text="", is_retweet=False, like_count=10, retweet_text=None):
    return Tweet(
        id=id, author="test", text=text,
        url=f"https://x.com/{id}", like_count=like_count,
        is_retweet=is_retweet, retweet_text=retweet_text,
    )


def test_passes_original_tweet_with_keyword():
    f = RelevanceFilter()
    tweet = _tweet(text="Claude 4 just launched with new reasoning!")
    assert f.filter([tweet]) == [tweet]


def test_drops_pure_retweet_with_no_commentary():
    f = RelevanceFilter()
    tweet = _tweet(
        text="RT @AnthropicAI: Claude 4 launched",
        is_retweet=True, retweet_text=None,
    )
    assert f.filter([tweet]) == []


def test_passes_retweet_with_commentary_and_keyword():
    f = RelevanceFilter()
    tweet = _tweet(
        text="RT @user: some text", is_retweet=True,
        retweet_text="This new model release changes everything!", like_count=0,
    )
    assert f.filter([tweet]) == [tweet]


def test_drops_retweet_below_engagement_threshold():
    f = RelevanceFilter(min_engagement=5)
    tweet = _tweet(
        text="RT @user: Claude launch", is_retweet=True,
        retweet_text=None, like_count=2,
    )
    assert f.filter([tweet]) == []


def test_drops_original_tweet_without_keyword():
    f = RelevanceFilter()
    tweet = _tweet(text="Just had a great coffee this morning!")
    assert f.filter([tweet]) == []


def test_keyword_match_is_case_insensitive():
    f = RelevanceFilter()
    tweet = _tweet(text="CLAUDE just dropped a new RELEASE!")
    assert f.filter([tweet]) == [tweet]


def test_empty_input_returns_empty():
    f = RelevanceFilter()
    assert f.filter([]) == []
