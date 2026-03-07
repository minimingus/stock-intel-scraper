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
                active      INTEGER NOT NULL DEFAULT 1,
                author_id   TEXT
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
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                tweet_id       TEXT NOT NULL,
                ticker         TEXT NOT NULL,
                asset_type     TEXT NOT NULL,
                sentiment      TEXT NOT NULL,
                trade_type     TEXT NOT NULL DEFAULT 'day',
                extracted_at   TEXT NOT NULL,
                target_price   REAL,
                ta_notes       TEXT,
                momentum_type  TEXT NOT NULL DEFAULT 'general'
            );
            CREATE TABLE IF NOT EXISTS paper_trades (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker            TEXT NOT NULL,
                expert_handle     TEXT NOT NULL,
                tweet_id          TEXT NOT NULL,
                entry_price       REAL NOT NULL,
                target_price      REAL,
                stop_price        REAL NOT NULL,
                signal_time       TEXT NOT NULL,
                opened_at         TEXT NOT NULL DEFAULT (datetime('now')),
                closed_at         TEXT,
                exit_price        REAL,
                outcome           TEXT NOT NULL DEFAULT 'open',
                pnl_pct           REAL,
                max_gain_pct      REAL,
                max_drawdown_pct  REAL,
                days_held         REAL,
                UNIQUE(tweet_id, ticker, expert_handle)
            );
            CREATE TABLE IF NOT EXISTS alerts_sent (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker     TEXT NOT NULL,
                sent_at    TEXT NOT NULL,
                expert_handles TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_sent_ticker_time
                ON alerts_sent (ticker, sent_at);
        """)
        # Migrate existing DBs
        for migration in [
            "ALTER TABLE experts ADD COLUMN author_id TEXT",
            "ALTER TABLE signals ADD COLUMN trade_type TEXT NOT NULL DEFAULT 'day'",
            "ALTER TABLE tweets ADD COLUMN tweet_time TEXT",
            "ALTER TABLE signals ADD COLUMN target_price REAL",
            "ALTER TABLE signals ADD COLUMN ta_notes TEXT",
            "ALTER TABLE signals ADD COLUMN momentum_type TEXT NOT NULL DEFAULT 'general'",
            "ALTER TABLE paper_trades ADD COLUMN max_gain_pct REAL",
            "ALTER TABLE paper_trades ADD COLUMN max_drawdown_pct REAL",
            "ALTER TABLE paper_trades ADD COLUMN days_held REAL",
            "CREATE TABLE IF NOT EXISTS alerts_sent (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, sent_at TEXT NOT NULL, expert_handles TEXT NOT NULL)",
            "CREATE INDEX IF NOT EXISTS idx_alerts_sent_ticker_time ON alerts_sent (ticker, sent_at)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_unique ON signals (tweet_id, ticker, asset_type)",
            "ALTER TABLE signals ADD COLUMN entry_price_suggested REAL",
            "ALTER TABLE signals ADD COLUMN stop_price_suggested REAL",
            "ALTER TABLE signals ADD COLUMN specificity INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE paper_trades ADD COLUMN trade_type TEXT NOT NULL DEFAULT 'swing'",
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

    def get_experts_without_tweets(self) -> list:
        """Return handles that have never been scraped (for backfill)."""
        rows = self.conn.execute("""
            SELECT e.handle FROM experts e
            WHERE e.active = 1
              AND NOT EXISTS (
                  SELECT 1 FROM tweets t WHERE t.handle = e.handle
              )
        """).fetchall()
        return [r["handle"] for r in rows]

    def get_active_experts(self) -> list:
        rows = self.conn.execute(
            "SELECT handle FROM experts WHERE active = 1"
        ).fetchall()
        return [r["handle"] for r in rows]

    def deactivate_expert(self, handle: str):
        self.conn.execute("UPDATE experts SET active = 0 WHERE handle = ?", (handle,))
        self.conn.commit()

    def set_author_id(self, handle: str, author_id: str):
        self.conn.execute(
            "UPDATE experts SET author_id = ? WHERE handle = ?", (author_id, handle)
        )
        self.conn.commit()

    def get_experts_with_author_ids(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT handle, author_id FROM experts WHERE active = 1 AND author_id IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]

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

    def get_tweets_without_crypto_signals(self) -> list:
        """Return tweets that have not yet been processed by the crypto extractor."""
        rows = self.conn.execute("""
            SELECT t.tweet_id, t.handle, t.text FROM tweets t
            LEFT JOIN signals s ON s.tweet_id = t.tweet_id AND s.asset_type = 'crypto'
            WHERE s.tweet_id IS NULL
        """).fetchall()
        return [dict(r) for r in rows]

    def insert_signal(self, tweet_id: str, ticker: str, asset_type: str, sentiment: str,
                      trade_type: str = "day", target_price: float = None, ta_notes: str = None,
                      momentum_type: str = "general", entry_price_suggested: float = None,
                      stop_price_suggested: float = None, specificity: int = 0):
        self.conn.execute(
            "INSERT OR IGNORE INTO signals (tweet_id, ticker, asset_type, sentiment, trade_type, extracted_at, "
            "target_price, ta_notes, momentum_type, entry_price_suggested, stop_price_suggested, specificity) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tweet_id, ticker, asset_type, sentiment, trade_type,
             datetime.now(timezone.utc).isoformat(), target_price, ta_notes, momentum_type,
             entry_price_suggested, stop_price_suggested, specificity),
        )
        self.conn.commit()

    def get_stock_signals_for_brief(self, lookback_hours: int = 24, min_expert_mentions: int = 1) -> list:
        """Ranked stock-only bullish signals aggregated by ticker."""
        rows = self.conn.execute("""
            SELECT s.ticker,
                   COUNT(DISTINCT t.handle) AS expert_count,
                   GROUP_CONCAT(DISTINCT t.handle) AS experts,
                   SUM(CASE WHEN s.trade_type = 'day' THEN 1 ELSE 0 END) AS day_count,
                   SUM(CASE WHEN s.trade_type = 'swing' THEN 1 ELSE 0 END) AS swing_count,
                   AVG(CASE WHEN s.target_price > 0 THEN s.target_price ELSE NULL END) AS avg_target,
                   GROUP_CONCAT(s.ta_notes, '|||') AS all_ta_notes,
                   MAX(COALESCE(t.tweet_time, t.scraped_at)) AS latest_signal_time,
                   CASE MAX(
                       CASE s.momentum_type
                           WHEN 'penny_pump' THEN 4
                           WHEN 'wave_play'  THEN 3
                           WHEN 'breakout'   THEN 2
                           ELSE 1 END)
                       WHEN 4 THEN 'penny_pump'
                       WHEN 3 THEN 'wave_play'
                       WHEN 2 THEN 'breakout'
                       ELSE 'general' END AS top_momentum_type,
                   AVG(CASE WHEN s.stop_price_suggested IS NOT NULL THEN s.stop_price_suggested END) AS expert_stop
            FROM signals s
            JOIN tweets t ON t.tweet_id = s.tweet_id
            WHERE s.extracted_at >= datetime('now', ?)
              AND s.sentiment = 'bullish'
              AND s.asset_type = 'stock'
            GROUP BY s.ticker
            HAVING COUNT(DISTINCT t.handle) >= ?
            ORDER BY expert_count DESC
            LIMIT 20
        """, (f"-{lookback_hours} hours", min_expert_mentions)).fetchall()
        return [dict(r) for r in rows]

    def get_crypto_signals_for_brief(self, lookback_hours: int = 24, min_expert_mentions: int = 1) -> list:
        """Ranked crypto-only bullish signals aggregated by ticker."""
        rows = self.conn.execute("""
            SELECT s.ticker,
                   COUNT(DISTINCT t.handle) AS expert_count,
                   GROUP_CONCAT(DISTINCT t.handle) AS experts,
                   SUM(CASE WHEN s.trade_type = 'day' THEN 1 ELSE 0 END) AS day_count,
                   SUM(CASE WHEN s.trade_type = 'swing' THEN 1 ELSE 0 END) AS swing_count,
                   AVG(CASE WHEN s.target_price > 0 THEN s.target_price ELSE NULL END) AS avg_target,
                   MAX(COALESCE(t.tweet_time, t.scraped_at)) AS latest_signal_time
            FROM signals s
            JOIN tweets t ON t.tweet_id = s.tweet_id
            WHERE s.extracted_at >= datetime('now', ?)
              AND s.sentiment = 'bullish'
              AND s.asset_type = 'crypto'
            GROUP BY s.ticker
            HAVING COUNT(DISTINCT t.handle) >= ?
            ORDER BY expert_count DESC
            LIMIT 20
        """, (f"-{lookback_hours} hours", min_expert_mentions)).fetchall()
        return [dict(r) for r in rows]

    def get_signals_with_handles(self, lookback_hours: int = 168) -> list:
        """Return bullish stock signals with expert handle and actual tweet timestamp."""
        rows = self.conn.execute("""
            SELECT s.ticker, s.asset_type, t.handle,
                   COALESCE(t.tweet_time, t.scraped_at) AS post_time
            FROM signals s
            JOIN tweets t ON t.tweet_id = s.tweet_id
            WHERE s.extracted_at >= datetime('now', ?)
              AND s.sentiment = 'bullish'
              AND s.asset_type = 'stock'
        """, (f"-{lookback_hours} hours",)).fetchall()
        return [dict(r) for r in rows]

    def get_new_signal_trades(self) -> list:
        """Return bullish stock signals that have no paper trade opened yet."""
        rows = self.conn.execute("""
            SELECT s.id AS signal_id, s.ticker, s.target_price, s.ta_notes,
                   s.entry_price_suggested, s.stop_price_suggested, s.trade_type,
                   t.handle, t.tweet_id,
                   COALESCE(t.tweet_time, t.scraped_at) AS signal_time
            FROM signals s
            JOIN tweets t ON t.tweet_id = s.tweet_id
            LEFT JOIN paper_trades pt
                   ON pt.tweet_id = s.tweet_id
                  AND pt.ticker = s.ticker
                  AND pt.expert_handle = t.handle
            WHERE s.sentiment = 'bullish'
              AND s.asset_type = 'stock'
              AND pt.id IS NULL
        """).fetchall()
        return [dict(r) for r in rows]

    def get_new_crypto_signal_trades(self) -> list:
        """Return bullish crypto signals that have no paper trade opened yet."""
        rows = self.conn.execute("""
            SELECT s.id AS signal_id, s.ticker, s.target_price, s.ta_notes,
                   t.handle, t.tweet_id,
                   COALESCE(t.tweet_time, t.scraped_at) AS signal_time
            FROM signals s
            JOIN tweets t ON t.tweet_id = s.tweet_id
            LEFT JOIN paper_trades pt
                   ON pt.tweet_id = s.tweet_id
                  AND pt.ticker = s.ticker
                  AND pt.expert_handle = t.handle
            WHERE s.sentiment = 'bullish'
              AND s.asset_type = 'crypto'
              AND pt.id IS NULL
        """).fetchall()
        return [dict(r) for r in rows]

    def open_paper_trade(self, ticker: str, expert_handle: str, tweet_id: str,
                         entry_price: float, target_price: float, stop_price: float,
                         signal_time: str, trade_type: str = "swing"):
        self.conn.execute(
            "INSERT OR IGNORE INTO paper_trades "
            "(ticker, expert_handle, tweet_id, entry_price, target_price, stop_price, "
            "signal_time, trade_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker, expert_handle, tweet_id, entry_price, target_price,
             stop_price, signal_time, trade_type),
        )
        self.conn.commit()

    def get_open_paper_trades(self) -> list:
        rows = self.conn.execute(
            "SELECT * FROM paper_trades WHERE outcome = 'open'"
        ).fetchall()
        return [dict(r) for r in rows]

    def close_paper_trade(self, trade_id: int, exit_price: float, outcome: str,
                          pnl_pct: float, max_gain_pct: float = None,
                          max_drawdown_pct: float = None, days_held: float = None):
        self.conn.execute(
            "UPDATE paper_trades SET closed_at = ?, exit_price = ?, outcome = ?, pnl_pct = ?, "
            "max_gain_pct = ?, max_drawdown_pct = ?, days_held = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), exit_price, outcome, pnl_pct,
             max_gain_pct, max_drawdown_pct, days_held, trade_id),
        )
        self.conn.commit()

    def get_expert_paper_scores(self) -> list:
        """Per-expert trading stats from closed paper trades. Requires >= 3 closed trades."""
        rows = self.conn.execute("""
            SELECT expert_handle,
                   COUNT(*) AS total,
                   SUM(CASE WHEN outcome = 'win'  THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) AS losses,
                   AVG(pnl_pct) AS avg_pnl_pct,
                   AVG(CASE WHEN outcome = 'win'  THEN pnl_pct END) AS avg_win_pct,
                   AVG(CASE WHEN outcome = 'loss' THEN pnl_pct END) AS avg_loss_pct,
                   AVG(max_gain_pct)     AS avg_max_gain,
                   AVG(max_drawdown_pct) AS avg_max_drawdown,
                   AVG(days_held)        AS avg_days_held,
                   SUM(CASE WHEN pnl_pct > 0 THEN pnl_pct  ELSE 0   END) AS gross_win,
                   SUM(CASE WHEN pnl_pct < 0 THEN -pnl_pct ELSE 0   END) AS gross_loss
            FROM paper_trades
            WHERE outcome != 'open'
            GROUP BY expert_handle
            HAVING COUNT(*) >= 3
            ORDER BY avg_pnl_pct DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def get_expert_trades_for_scoring(self) -> list:
        """Return individual closed trades with dates and OHLC stats for time-decay scoring."""
        rows = self.conn.execute("""
            SELECT expert_handle, outcome, pnl_pct, closed_at,
                   max_gain_pct, max_drawdown_pct, days_held
            FROM paper_trades
            WHERE outcome != 'open' AND pnl_pct IS NOT NULL
            ORDER BY expert_handle, closed_at DESC
        """).fetchall()
        return [dict(r) for r in rows]

    # kept for compatibility with old scorer
    def get_signals_for_brief(self, lookback_hours: int = 24, min_expert_mentions: int = 1) -> list:
        return self.get_stock_signals_for_brief(lookback_hours, min_expert_mentions)

    def prune_old_tweets(self, days: int = 7):
        self.conn.execute(
            "DELETE FROM tweets WHERE scraped_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        self.conn.commit()

    def prune_old_alerts(self, days: int = 1):
        self.conn.execute(
            "DELETE FROM alerts_sent WHERE sent_at < datetime('now', ?)",
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

    def get_ticker_paper_history(self, ticker: str) -> dict | None:
        """Win/loss/avg-pnl history for a specific ticker across all closed paper trades."""
        row = self.conn.execute("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN outcome = 'win'  THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) AS losses,
                   AVG(pnl_pct) AS avg_pnl_pct
            FROM paper_trades
            WHERE ticker = ? AND outcome != 'open'
        """, (ticker,)).fetchone()
        if not row or not row["total"]:
            return None
        return dict(row)

    def get_expert_recent_trades(self, handle: str, limit: int = 5) -> list:
        """Return last N closed paper trades for an expert."""
        rows = self.conn.execute("""
            SELECT ticker, outcome, pnl_pct, closed_at
            FROM paper_trades
            WHERE expert_handle = ? AND outcome != 'open'
            ORDER BY closed_at DESC
            LIMIT ?
        """, (handle, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_portfolio_summary(self) -> dict:
        """Cumulative P&L across all closed paper trades."""
        row = self.conn.execute("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN outcome = 'win'      THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN outcome = 'loss'     THEN 1 ELSE 0 END) AS losses,
                   SUM(CASE WHEN outcome = 'expired'  THEN 1 ELSE 0 END) AS expired,
                   AVG(pnl_pct) AS avg_pnl_pct,
                   SUM(pnl_pct) AS cumulative_pnl
            FROM paper_trades WHERE outcome != 'open'
        """).fetchone()
        if not row or not row["total"]:
            return {}
        return dict(row)

    def was_alert_sent_recently(self, ticker: str, within_hours: int = 4) -> bool:
        row = self.conn.execute("""
            SELECT 1 FROM alerts_sent
            WHERE ticker = ? AND sent_at >= datetime('now', ?)
            LIMIT 1
        """, (ticker, f"-{within_hours} hours")).fetchone()
        return row is not None

    def record_alert_sent(self, ticker: str, expert_handles: list):
        handles_str = ",".join(str(h) for h in expert_handles) if expert_handles else ""
        self.conn.execute(
            "INSERT INTO alerts_sent (ticker, sent_at, expert_handles) VALUES (?, ?, ?)",
            (ticker, datetime.now(timezone.utc).isoformat(), handles_str),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
