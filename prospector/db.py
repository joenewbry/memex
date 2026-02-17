import aiosqlite
import json
import time
from pathlib import Path
from adapters.base import Prospect

DB_PATH = Path(__file__).parent / "data" / "prospector.db"


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'running',
                started_at REAL,
                finished_at REAL,
                adapters_used TEXT,
                log TEXT
            );
            CREATE TABLE IF NOT EXISTS prospects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                source TEXT NOT NULL,
                username TEXT NOT NULL,
                display_name TEXT,
                profile_url TEXT,
                bio TEXT,
                category TEXT,
                signals TEXT,
                raw_data TEXT,
                trust_gap_score REAL DEFAULT 0,
                reachability_score REAL DEFAULT 0,
                relevance_score REAL DEFAULT 0,
                final_score REAL DEFAULT 0,
                outreach_message TEXT,
                deep_profile TEXT,
                fetched_at REAL,
                FOREIGN KEY (run_id) REFERENCES runs(id)
            );
            CREATE INDEX IF NOT EXISTS idx_prospects_run ON prospects(run_id);
            CREATE INDEX IF NOT EXISTS idx_prospects_score ON prospects(final_score DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_prospects_source_user_run
                ON prospects(run_id, source, username);
        """)


async def save_run(run_id: str, status: str, started_at: float,
                   finished_at: float = None, adapters_used: list = None, log: list = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO runs (id, status, started_at, finished_at, adapters_used, log)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (run_id, status, started_at, finished_at,
              json.dumps(adapters_used or []), json.dumps(log or [])))
        await db.commit()


async def save_prospects(run_id: str, prospects: list[Prospect]):
    async with aiosqlite.connect(DB_PATH) as db:
        for p in prospects:
            await db.execute("""
                INSERT OR REPLACE INTO prospects
                (run_id, source, username, display_name, profile_url, bio, category,
                 signals, raw_data, trust_gap_score, reachability_score, relevance_score,
                 final_score, outreach_message, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, p.source, p.username, p.display_name, p.profile_url,
                  p.bio, p.category, json.dumps(p.signals), json.dumps(p.raw_data),
                  p.trust_gap_score, p.reachability_score, p.relevance_score,
                  p.final_score, p.outreach_message, p.fetched_at))
        await db.commit()


async def update_prospect_outreach(prospect_id: int, message: str, deep_profile: dict = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE prospects SET outreach_message = ?, deep_profile = ? WHERE id = ?
        """, (message, json.dumps(deep_profile) if deep_profile else None, prospect_id))
        await db.commit()


async def get_all_runs():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT r.*, COUNT(p.id) as prospect_count
            FROM runs r LEFT JOIN prospects p ON r.id = p.run_id
            GROUP BY r.id ORDER BY r.started_at DESC
        """)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_run_prospects(run_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM prospects WHERE run_id = ? ORDER BY final_score DESC
        """, (run_id,))
        rows = await cursor.fetchall()
        return [_row_to_prospect_dict(dict(r)) for r in rows]


async def get_all_prospects():
    """Get all prospects across all runs, deduped by source+username, keeping highest score."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT p.*, r.started_at as run_started_at
            FROM prospects p
            JOIN runs r ON p.run_id = r.id
            WHERE p.id IN (
                SELECT id FROM prospects p2
                WHERE p2.source = p.source AND p2.username = p.username
                ORDER BY p2.final_score DESC LIMIT 1
            )
            ORDER BY p.final_score DESC
        """)
        rows = await cursor.fetchall()
        return [_row_to_prospect_dict(dict(r)) for r in rows]


async def get_prospect_by_id(prospect_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM prospects WHERE id = ?", (prospect_id,))
        row = await cursor.fetchone()
        if row:
            return _row_to_prospect_dict(dict(row))
        return None


def _row_to_prospect_dict(row: dict) -> dict:
    row["signals"] = json.loads(row.get("signals") or "[]")
    row["raw_data"] = json.loads(row.get("raw_data") or "{}")
    row["deep_profile"] = json.loads(row.get("deep_profile") or "null")
    return row


async def get_daily_prospect_counts(days: int = 30) -> list[dict]:
    """Get number of prospects found per day."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("""
            SELECT date(fetched_at, 'unixepoch') as date, COUNT(*) as count
            FROM prospects
            WHERE fetched_at > (strftime('%s', 'now') - ? * 86400)
            GROUP BY date(fetched_at, 'unixepoch')
            ORDER BY date
        """, (days,))
        return [dict(r) for r in await cursor.fetchall()]


async def get_daily_run_counts(days: int = 30) -> list[dict]:
    """Get number of pipeline runs per day."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("""
            SELECT date(started_at, 'unixepoch') as date, COUNT(*) as count
            FROM runs
            WHERE started_at > (strftime('%s', 'now') - ? * 86400)
            GROUP BY date(started_at, 'unixepoch')
            ORDER BY date
        """, (days,))
        return [dict(r) for r in await cursor.fetchall()]


async def get_stats_summary() -> dict:
    """Get aggregate stats for the stats page."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row

        cur = await conn.execute("SELECT COUNT(*) as total FROM prospects")
        total_prospects = (await cur.fetchone())["total"]

        cur = await conn.execute("SELECT COUNT(*) as total FROM prospects WHERE outreach_message IS NOT NULL AND outreach_message != ''")
        total_outreach = (await cur.fetchone())["total"]

        cur = await conn.execute("SELECT COUNT(*) as total FROM runs")
        total_runs = (await cur.fetchone())["total"]

        cur = await conn.execute("""
            SELECT source, COUNT(*) as count, AVG(final_score) as avg_score
            FROM prospects GROUP BY source ORDER BY count DESC
        """)
        by_source = [dict(r) for r in await cur.fetchall()]

        cur = await conn.execute("""
            SELECT category, COUNT(*) as count, AVG(final_score) as avg_score
            FROM prospects WHERE category IS NOT NULL AND category != ''
            GROUP BY category ORDER BY count DESC
        """)
        by_category = [dict(r) for r in await cur.fetchall()]

        cur = await conn.execute("""
            SELECT
                CASE
                    WHEN final_score < 0.2 THEN '0.0-0.2'
                    WHEN final_score < 0.4 THEN '0.2-0.4'
                    WHEN final_score < 0.6 THEN '0.4-0.6'
                    WHEN final_score < 0.8 THEN '0.6-0.8'
                    ELSE '0.8-1.0'
                END as bucket,
                COUNT(*) as count
            FROM prospects GROUP BY bucket ORDER BY bucket
        """)
        score_dist = [dict(r) for r in await cur.fetchall()]

        return {
            "total_prospects": total_prospects,
            "total_outreach": total_outreach,
            "total_runs": total_runs,
            "by_source": by_source,
            "by_category": by_category,
            "score_distribution": score_dist,
        }
