"""SQLite storage for digest runs and per-post summaries."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.pipeline.types import ArticleSummary, PostSummary
from app.storage.posts import _connect, _ensure_schema as _ensure_posts_schema

_CREATE_DIGEST_RUNS = """
CREATE TABLE digest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    posts_collected INTEGER NOT NULL DEFAULT 0,
    categories_count INTEGER NOT NULL DEFAULT 0,
    run_type TEXT NOT NULL DEFAULT 'full'
)
"""

_CREATE_POST_SUMMARIES = """
CREATE TABLE post_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    channel TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    url TEXT NOT NULL,
    rank INTEGER NOT NULL,
    FOREIGN KEY (run_id) REFERENCES digest_runs(id)
)
"""

_CREATE_POST_SUMMARIES_ALL = """
CREATE TABLE post_summaries_all (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    channel TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    url TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    reactions INTEGER NOT NULL DEFAULT 0,
    replies INTEGER NOT NULL DEFAULT 0,
    engagement_score REAL NOT NULL DEFAULT 0,
    llm_relevance REAL NOT NULL DEFAULT 0,
    combined_score REAL NOT NULL DEFAULT 0,
    post_date TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES digest_runs(id),
    UNIQUE(run_id, url)
)
"""


def _ensure_summary_schema(conn: sqlite3.Connection) -> None:
    _ensure_posts_schema(conn)
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='digest_runs'"
    ).fetchone() is None:
        conn.execute(_CREATE_DIGEST_RUNS)
    else:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(digest_runs)").fetchall()}
        if "run_type" not in cols:
            conn.execute("ALTER TABLE digest_runs ADD COLUMN run_type TEXT NOT NULL DEFAULT 'full'")

    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='post_summaries'"
    ).fetchone() is None:
        conn.execute(_CREATE_POST_SUMMARIES)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_post_summaries_run_category "
            "ON post_summaries(run_id, category, rank)"
        )
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='post_summaries_all'"
    ).fetchone() is None:
        conn.execute(_CREATE_POST_SUMMARIES_ALL)


def start_digest_run(
    sqlite_path: str,
    *,
    posts_collected: int,
    categories_count: int,
    run_type: str = "full",
) -> int:
    conn = _connect(sqlite_path)
    try:
        _ensure_summary_schema(conn)
        cur = conn.execute(
            """
            INSERT INTO digest_runs (started_at, posts_collected, categories_count, run_type)
            VALUES (?, ?, ?, ?)
            """,
            (datetime.now(timezone.utc).isoformat(), posts_collected, categories_count, run_type),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def finish_digest_run(sqlite_path: str, run_id: int) -> None:
    conn = _connect(sqlite_path)
    try:
        _ensure_summary_schema(conn)
        conn.execute(
            "UPDATE digest_runs SET finished_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), run_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_run_id(sqlite_path: str, *, run_type: str | None = None) -> int | None:
    conn = _connect(sqlite_path)
    try:
        _ensure_summary_schema(conn)
        if run_type:
            row = conn.execute(
                "SELECT MAX(id) FROM digest_runs WHERE run_type = ?",
                (run_type,),
            ).fetchone()
        else:
            row = conn.execute("SELECT MAX(id) FROM digest_runs").fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])
    finally:
        conn.close()


def save_article_summaries(sqlite_path: str, run_id: int, articles: list[ArticleSummary]) -> int:
    conn = _connect(sqlite_path)
    inserted = 0
    try:
        _ensure_summary_schema(conn)
        conn.execute("DELETE FROM post_summaries_all WHERE run_id = ?", (run_id,))
        for item in articles:
            conn.execute(
                """
                INSERT OR REPLACE INTO post_summaries_all (
                    run_id, category, channel, title, summary, url,
                    views, reactions, replies,
                    engagement_score, llm_relevance, combined_score, post_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    item.category,
                    item.channel,
                    item.title,
                    item.summary,
                    item.url,
                    item.views,
                    item.reactions,
                    item.replies,
                    item.engagement_score,
                    item.llm_relevance,
                    item.combined_score,
                    item.post_date.isoformat(),
                ),
            )
            inserted += 1
        conn.commit()
    finally:
        conn.close()
    return inserted


def load_article_summaries_grouped(sqlite_path: str, run_id: int) -> dict[str, list[dict]]:
    conn = _connect(sqlite_path)
    try:
        _ensure_summary_schema(conn)
        rows = conn.execute(
            """
            SELECT category, channel, title, summary, url,
                   views, reactions, replies,
                   engagement_score, llm_relevance, combined_score, post_date
            FROM post_summaries_all
            WHERE run_id = ?
            ORDER BY category, combined_score DESC
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    result: dict[str, list[dict]] = {}
    for row in rows:
        category = str(row[0])
        result.setdefault(category, []).append(
            {
                "category": category,
                "channel": str(row[1]),
                "title": str(row[2]),
                "summary": str(row[3]),
                "url": str(row[4]),
                "views": int(row[5]),
                "reactions": int(row[6]),
                "replies": int(row[7]),
                "engagement_score": float(row[8]),
                "llm_relevance": float(row[9]),
                "combined_score": float(row[10]),
                "date": row[11],
            }
        )
    return result


def save_post_summaries(sqlite_path: str, run_id: int, summaries: list[PostSummary]) -> int:
    conn = _connect(sqlite_path)
    inserted = 0
    try:
        _ensure_summary_schema(conn)
        conn.execute("DELETE FROM post_summaries WHERE run_id = ?", (run_id,))
        for item in summaries:
            conn.execute(
                """
                INSERT INTO post_summaries (
                    run_id, category, channel, title, summary, url, rank
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, item.category, item.channel, item.title, item.summary, item.url, item.rank),
            )
            inserted += 1
        conn.commit()
    finally:
        conn.close()
    return inserted


def load_post_summaries(sqlite_path: str, run_id: int) -> dict[str, list[PostSummary]]:
    conn = _connect(sqlite_path)
    try:
        _ensure_summary_schema(conn)
        rows = conn.execute(
            """
            SELECT category, channel, title, summary, url, rank
            FROM post_summaries
            WHERE run_id = ?
            ORDER BY category, rank
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    result: dict[str, list[PostSummary]] = {}
    for category, channel, title, summary, url, rank in rows:
        result.setdefault(str(category), []).append(
            PostSummary(
                category=str(category),
                channel=str(channel),
                title=str(title),
                summary=str(summary),
                url=str(url),
                rank=int(rank),
            )
        )
    return result


def delete_old_runs(sqlite_path: str, keep_run_ids: set[int]) -> int:
    if not keep_run_ids:
        return 0
    conn = _connect(sqlite_path)
    try:
        _ensure_summary_schema(conn)
        placeholders = ",".join("?" for _ in keep_run_ids)
        params = list(keep_run_ids)
        conn.execute(f"DELETE FROM post_summaries WHERE run_id NOT IN ({placeholders})", params)
        conn.execute(f"DELETE FROM post_summaries_all WHERE run_id NOT IN ({placeholders})", params)
        conn.execute(f"DELETE FROM digest_runs WHERE id NOT IN ({placeholders})", params)
        conn.commit()
        return 1
    finally:
        conn.close()
