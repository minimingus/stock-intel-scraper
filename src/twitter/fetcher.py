import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

from twikit import Client

from src.twitter.filter import Tweet
from src.twitter.signal_store import SignalStore

COOKIES_PATH = Path("data/twitter_cookies.json")


class TweetFetcher:
    def __init__(
        self,
        username: str,
        password: str,
        email: str,
        cookies_path: Path = COOKIES_PATH,
    ):
        self._username = username
        self._password = password
        self._email = email
        self._cookies_path = cookies_path
        self._client = Client("en-US")

    async def _ensure_authenticated(self) -> None:
        if self._cookies_path.exists():
            self._client.load_cookies(str(self._cookies_path))
        else:
            await self._client.login(
                auth_info_1=self._username,
                auth_info_2=self._email,
                password=self._password,
            )
            self._cookies_path.parent.mkdir(parents=True, exist_ok=True)
            self._client.save_cookies(str(self._cookies_path))

    async def _fetch_user_tweets(
        self, screen_name: str, since_hours: int
    ) -> list[Tweet]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        try:
            user = await self._client.get_user_by_screen_name(screen_name)
            raw_tweets = await user.get_tweets("Tweets", count=40)
        except Exception:
            return []

        tweets = []
        for t in raw_tweets:
            if t.created_at_datetime and t.created_at_datetime < cutoff:
                continue
            is_retweet = t.retweeted_tweet is not None
            retweet_text = None
            if is_retweet and t.full_text and not t.full_text.startswith("RT "):
                retweet_text = t.full_text
            tweets.append(
                Tweet(
                    id=t.id,
                    author=screen_name,
                    text=t.full_text or "",
                    url=f"https://x.com/{screen_name}/status/{t.id}",
                    like_count=t.favorite_count or 0,
                    is_retweet=is_retweet,
                    retweet_text=retweet_text,
                )
            )
        return tweets

    async def _fetch_all(
        self, accounts: list[str], since_hours: int
    ) -> list[Tweet]:
        await self._ensure_authenticated()
        results: list[Tweet] = []
        for account in accounts:
            results.extend(await self._fetch_user_tweets(account, since_hours))
        return results

    def fetch(
        self,
        accounts: list[str],
        since_hours: int,
        store: SignalStore | None = None,
    ) -> list[Tweet]:
        """Synchronous wrapper. Deduplicates against store if provided."""
        tweets = asyncio.run(self._fetch_all(accounts, since_hours))
        if store is None:
            return tweets
        new_tweets = [t for t in tweets if not store.is_seen(t.id)]
        store.mark_seen([t.id for t in new_tweets])
        return new_tweets
