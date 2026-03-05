import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class TwitterIntelStore:
    def __init__(self, db_path: str = "data/twitter_intel.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS experts (
                handle      TEXT PRIMARY KEY,
                source      TEXT NOT NULL,
                added_date  TEXT NOT NULL,
                active      INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS tweets (
                tweet_id    TEXT PRIMARY KEY,
                handle      TEXT NOT NULL,
                text        TEXT NOT NULL,
                likes       INTEGER NOT NULL DEFAULT 0,
                retweets    INTEGER NOT NULL DEFAULT 0,
                scraped_at  TEXT NOT NULL,
                tweet_time  TEXT
            );
            CREATE TABLE IF NOT EXISTS signals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                tweet_id     TEXT NOT NULL,
                ticker       TEXT NOT NULL,
                asset_type   TEXT NOT NULL,
                sentiment    TEXT NOT NULL,
                trade_type   TEXT NOT NULL DEFAULT 'day',
                extracted_at TEXT NOT NULL
            );
        """)
        # Migrate existing DBs
        for migration in [
            "ALTER TABLE signals ADD COLUMN trade_type TEXT NOT NULL DEFAULT 'day'",
            "ALTER TABLE tweets ADD COLUMN tweet_time TEXT",
        ]:
            try:
                self.conn.execute(migration)
                self.conn.commit()
            except Exception:
                pass  # column already exists

    def upsert_expert(self, handle: str, source: str = "seed"):
        self.conn.execute(
            "INSERT OR IGNORE INTO experts (handle, source, added_date, active) VALUES (?, ?, ?, 1)",
            (handle, source, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def get_active_experts(self) -> list:
        rows = self.conn.execute(
            "SELECT handle FROM experts WHERE active = 1"
        ).fetchall()
        return [r["handle"] for r in rows]

    def insert_tweet(self, tweet_id: str, handle: str, text: str, likes: int, retweets: int, tweet_time: str = None):
        self.conn.execute(
            "INSERT OR IGNORE INTO tweets (tweet_id, handle, text, likes, retweets, scraped_at, tweet_time) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tweet_id, handle, text, likes, retweets, datetime.now(timezone.utc).isoformat(), tweet_time),
        )
        self.conn.commit()

    def get_new_tweets(self) -> list:
        """Return tweets not yet processed by signal extraction."""
        rows = self.conn.execute("""
            SELECT t.tweet_id, t.handle, t.text FROM tweets t
            LEFT JOIN signals s ON s.tweet_id = t.tweet_id
            WHERE s.tweet_id IS NULL
        """).fetchall()
        return [dict(r) for r in rows]

    def insert_signal(self, tweet_id: str, ticker: str, asset_type: str, sentiment: str, trade_type: str = "day"):
        self.conn.execute(
            "INSERT INTO signals (tweet_id, ticker, asset_type, sentiment, trade_type, extracted_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tweet_id, ticker, asset_type, sentiment, trade_type, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def get_signals_for_brief(self, lookback_hours: int = 24, min_expert_mentions: int = 1) -> list:
        """Ranked signals: tickers mentioned by most distinct experts in the window."""
        rows = self.conn.execute("""
            SELECT s.ticker, s.asset_type,
                   COUNT(DISTINCT t.handle) AS expert_count,
                   GROUP_CONCAT(DISTINCT t.handle) AS experts,
                   SUM(CASE WHEN s.sentiment = 'bullish' THEN 1 ELSE 0 END) AS bullish_count,
                   SUM(CASE WHEN s.sentiment = 'bearish' THEN 1 ELSE 0 END) AS bearish_count,
                   SUM(CASE WHEN s.trade_type = 'day' THEN 1 ELSE 0 END) AS day_count,
                   SUM(CASE WHEN s.trade_type = 'swing' THEN 1 ELSE 0 END) AS swing_count
            FROM signals s
            JOIN tweets t ON t.tweet_id = s.tweet_id
            WHERE s.extracted_at >= datetime('now', ?)
              AND s.sentiment = 'bullish'
            GROUP BY s.ticker, s.asset_type
            HAVING COUNT(DISTINCT t.handle) >= ?
            ORDER BY expert_count DESC
        """, (f"-{lookback_hours} hours", min_expert_mentions)).fetchall()
        return [dict(r) for r in rows]

    def get_signals_with_handles(self, lookback_hours: int = 168) -> list:
        """Return bullish signals with expert handle and actual tweet timestamp."""
        rows = self.conn.execute("""
            SELECT s.ticker, s.asset_type, t.handle,
                   COALESCE(t.tweet_time, t.scraped_at) AS post_time
            FROM signals s
            JOIN tweets t ON t.tweet_id = s.tweet_id
            WHERE s.extracted_at >= datetime('now', ?)
              AND s.sentiment = 'bullish'
        """, (f"-{lookback_hours} hours",)).fetchall()
        return [dict(r) for r in rows]

    def prune_old_tweets(self, days: int = 7):
        self.conn.execute(
            "DELETE FROM tweets WHERE scraped_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        self.conn.commit()

    def get_expert_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM experts WHERE active = 1"
        ).fetchone()[0]

    def get_tweet_count_24h(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM tweets WHERE scraped_at >= datetime('now', '-24 hours')"
        ).fetchone()[0]

    def close(self):
        self.conn.close()
