import sqlite3
from typing import Optional, List, Dict, Any, Tuple

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "data", "state")
DB_PATH = os.path.join(STATE_DIR, "iiko_matcher.db")


def normalize_item_name(name: str) -> str:
    """Removes non-breaking spaces and normalizes contiguous whitespace."""
    if not name:
        return ""
    return " ".join(name.replace("\xa0", " ").strip().split())


def get_db_connection() -> sqlite3.Connection:
    """Provides thread-safe connection with Write-Ahead Logging and timeout."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db():
    os.makedirs(STATE_DIR, exist_ok=True)
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. Product mapping consensus table with usage tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS supplier_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id TEXT NOT NULL,
                raw_name TEXT NOT NULL,
                product_id TEXT NOT NULL,
                iiko_name TEXT NOT NULL,
                iiko_article TEXT,
                usage_count INTEGER DEFAULT 1,
                last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(supplier_id, raw_name, product_id)
            )
        """)

        # 2. Preferred suppliers lookup table for disambiguating identical INNs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS preferred_suppliers (
                inn TEXT PRIMARY KEY,
                supplier_id TEXT NOT NULL,
                supplier_name TEXT NOT NULL
            )
        """)

        # 3. Gemini API key usage telemetry table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gemini_key_stats (
                key_name TEXT PRIMARY KEY,
                total_requests INTEGER DEFAULT 0,
                successful_requests INTEGER DEFAULT 0,
                rate_limit_hits INTEGER DEFAULT 0,
                last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def record_mapping_vote(
    supplier_id: str,
    raw_name: str,
    product_id: str,
    iiko_name: str,
    article: str = "",
    weight: int = 1,
):
    clean_name = normalize_item_name(raw_name)
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO supplier_mappings 
            (supplier_id, raw_name, product_id, iiko_name, iiko_article, usage_count, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(supplier_id, raw_name, product_id) 
            DO UPDATE SET 
                usage_count = usage_count + ?,
                last_used_at = CURRENT_TIMESTAMP
        """,
            (
                supplier_id,
                clean_name,
                product_id,
                iiko_name,
                article,
                weight,
                weight,
            ),
        )


def get_consensus_mapping(supplier_id: str, raw_name: str) -> Optional[Dict[str, Any]]:
    clean_name = normalize_item_name(raw_name)
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT product_id, iiko_name, iiko_article, usage_count
            FROM supplier_mappings
            WHERE supplier_id = ? AND raw_name = ?
            ORDER BY usage_count DESC, last_used_at DESC
        """,
            (supplier_id, clean_name),
        )
        rows = cur.fetchall()

        if not rows:
            return None

        total_votes = sum(r[3] for r in rows)
        winner = rows[0]
        confidence = winner[3] / total_votes

        return {
            "product_id": winner[0],
            "iiko_name": winner[1],
            "iiko_article": winner[2],
            "votes": winner[3],
            "total_votes": total_votes,
            "confidence": confidence,
            "has_conflict": len(rows) > 1 and confidence < 0.75,
            "all_variants": rows,
        }


def save_preferred_supplier(inn: str, supplier_id: str, supplier_name: str):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO preferred_suppliers (inn, supplier_id, supplier_name) VALUES (?, ?, ?)",
            (inn, supplier_id, supplier_name),
        )


def get_preferred_supplier(inn: str) -> Optional[Tuple[str, str]]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT supplier_id, supplier_name FROM preferred_suppliers WHERE inn = ?",
            (inn,),
        )
        return cur.fetchone()


def record_gemini_key_stat(key_name: str, success: bool, is_rate_limit: bool = False):
    """Records key usage metrics transactionally."""
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO gemini_key_stats (key_name, total_requests, successful_requests, rate_limit_hits, last_used_at)
            VALUES (?, 1, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key_name) DO UPDATE SET
                total_requests = total_requests + 1,
                successful_requests = successful_requests + ?,
                rate_limit_hits = rate_limit_hits + ?,
                last_used_at = CURRENT_TIMESTAMP
        """,
            (
                key_name,
                1 if success else 0,
                1 if is_rate_limit else 0,
                1 if success else 0,
                1 if is_rate_limit else 0,
            ),
        )


def get_gemini_key_usage_counts() -> Dict[str, int]:
    """Returns mapping of key_name to total number of requests."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT key_name, total_requests FROM gemini_key_stats")
        return dict(cur.fetchall())


def get_all_gemini_key_stats() -> List[Tuple[str, int, int, int, str]]:
    """Returns full reporting metrics for all tracked API keys."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT key_name, total_requests, successful_requests, rate_limit_hits, last_used_at
            FROM gemini_key_stats
            ORDER BY total_requests DESC
        """)
        return cur.fetchall()


if __name__ == "__main__":
    init_db()
    print("[+] Database initialized successfully.")
