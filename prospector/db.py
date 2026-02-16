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
