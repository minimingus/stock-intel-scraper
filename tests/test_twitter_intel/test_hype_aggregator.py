from src.twitter_intel.hype_aggregator import aggregate_hype, filter_penny_pumps


def test_aggregate_hype_counts_and_deduplicates():
    mentions = [
        {"ticker": "TSLA", "handle": "alice", "tweet_time": "2026-03-09T10:00:00+00:00"},
        {"ticker": "TSLA", "handle": "alice", "tweet_time": "2026-03-09T11:00:00+00:00"},  # same handle twice
        {"ticker": "TSLA", "handle": "bob",   "tweet_time": "2026-03-09T10:30:00+00:00"},
        {"ticker": "NVDA", "handle": "alice", "tweet_time": "2026-03-09T09:00:00+00:00"},
    ]
    result = aggregate_hype(mentions)
    assert result[0]["ticker"] == "TSLA"
    assert result[0]["count"] == 2          # alice counted once, bob once
    assert set(result[0]["handles"]) == {"alice", "bob"}
    assert result[1]["ticker"] == "NVDA"
    assert result[1]["count"] == 1


def test_aggregate_hype_sorted_by_count_desc():
    mentions = [
        {"ticker": "A", "handle": "x", "tweet_time": "t"},
        {"ticker": "B", "handle": "x", "tweet_time": "t"},
        {"ticker": "B", "handle": "y", "tweet_time": "t"},
        {"ticker": "B", "handle": "z", "tweet_time": "t"},
    ]
    result = aggregate_hype(mentions)
    assert result[0]["ticker"] == "B"


def test_filter_penny_pumps_separates_by_threshold():
    hype = [
        {"ticker": "ONDS",  "count": 5, "handles": ["a"]},
        {"ticker": "TSLA",  "count": 3, "handles": ["b"]},
        {"ticker": "EVTV",  "count": 2, "handles": ["c"]},
    ]

    def mock_fetch(ticker):
        return {
            "ONDS":  {"price": 0.91, "mktcap": 42_000_000},
            "TSLA":  {"price": 392.0, "mktcap": 1_200_000_000_000},
            "EVTV":  {"price": 2.10, "mktcap": 67_000_000},
        }.get(ticker, {})

    pennies, stocks = filter_penny_pumps(hype, fetcher=mock_fetch)
    assert [p["ticker"] for p in pennies] == ["ONDS", "EVTV"]
    assert [s["ticker"] for s in stocks]  == ["TSLA"]


def test_filter_penny_pumps_skips_fetch_failures():
    hype = [{"ticker": "BROKEN", "count": 3, "handles": ["x"]}]
    pennies, stocks = filter_penny_pumps(hype, fetcher=lambda t: {})
    # unknown price → treat as non-penny, include in stocks
    assert stocks[0]["ticker"] == "BROKEN"
    assert pennies == []
