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

        # 1. Product mapping consensus table with usage tracking and packaging coefficient
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS supplier_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id TEXT NOT NULL,
                raw_name TEXT NOT NULL,
                product_id TEXT NOT NULL,
                iiko_name TEXT NOT NULL,
                iiko_article TEXT,
                usage_count INTEGER DEFAULT 1,
                package_coefficient REAL NOT NULL DEFAULT 1.0,
                last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(supplier_id, raw_name, product_id)
            )
        """)

        # Migration: ensure package_coefficient column exists in legacy tables
        cursor.execute("PRAGMA table_info(supplier_mappings)")
        mapping_columns = [row[1] for row in cursor.fetchall()]
        if "package_coefficient" not in mapping_columns:
            cursor.execute("ALTER TABLE supplier_mappings ADD COLUMN package_coefficient REAL NOT NULL DEFAULT 1.0")

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

        # 4. Telegram bot authorized users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 5. One-time invitation tokens for secure onboarding
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_invites (
                token TEXT PRIMARY KEY,
                created_by INTEGER NOT NULL,
                used_by INTEGER,
                is_used INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_at TIMESTAMP
            )
        """)

        # 6. Dynamically managed restaurant delivery stores
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS managed_stores (
                store_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Seed initial stores from configuration if table is clean
        cursor.execute("SELECT COUNT(*) FROM managed_stores")
        if cursor.fetchone()[0] == 0:
            from config import STORES_CONFIG
            for s_id, s_data in STORES_CONFIG.items():
                cursor.execute(
                    "INSERT INTO managed_stores (store_id, name, is_active) VALUES (?, ?, 1)",
                    (s_id, s_data["name"])
                )
        conn.commit()


def record_mapping_vote(
    supplier_id: str,
    raw_name: str,
    product_id: str,
    iiko_name: str,
    article: str = "",
    weight: int = 1,
    package_coefficient: float = 1.0,
):
    clean_name = normalize_item_name(raw_name)
    safe_coeff = float(package_coefficient) if package_coefficient and package_coefficient > 0 else 1.0
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO supplier_mappings 
            (supplier_id, raw_name, product_id, iiko_name, iiko_article, usage_count, package_coefficient, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(supplier_id, raw_name, product_id) 
            DO UPDATE SET 
                usage_count = usage_count + ?,
                package_coefficient = excluded.package_coefficient,
                last_used_at = CURRENT_TIMESTAMP
        """,
            (
                supplier_id,
                clean_name,
                product_id,
                iiko_name,
                article,
                weight,
                safe_coeff,
                weight,
            ),
        )


def get_consensus_mapping(supplier_id: str, raw_name: str) -> Optional[Dict[str, Any]]:
    clean_name = normalize_item_name(raw_name)
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT product_id, iiko_name, iiko_article, usage_count, package_coefficient
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
        coeff = winner[4] if len(winner) > 4 and winner[4] else 1.0

        return {
            "product_id": winner[0],
            "iiko_name": winner[1],
            "iiko_article": winner[2],
            "votes": winner[3],
            "package_coefficient": float(coeff),
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


# ================= TELEGRAM ACCESS CONTROL REPOSITORY =================
def get_bot_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves an active bot user by Telegram ID."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT telegram_id, username, full_name, role, is_active FROM bot_users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "telegram_id": row[0],
            "username": row[1],
            "full_name": row[2],
            "role": row[3],
            "is_active": bool(row[4]),
        }


def upsert_bot_user(telegram_id: int, username: Optional[str], full_name: str, role: str = "user"):
    """Creates or updates a bot user record."""
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO bot_users (telegram_id, username, full_name, role, is_active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                role = excluded.role,
                is_active = 1
        """,
            (telegram_id, username, full_name, role),
        )


def create_invite_token(created_by: int) -> str:
    """Generates and persists a unique single-use invitation token."""
    import secrets

    token = secrets.token_urlsafe(16)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO bot_invites (token, created_by, is_used) VALUES (?, ?, 0)",
            (token, created_by),
        )
    return token


def validate_and_consume_invite(
    token: str, telegram_id: int, username: Optional[str], full_name: str
) -> bool:
    """Validates single-use token and registers new user transactionally."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT token, is_used FROM bot_invites WHERE token = ?", (token,)
        )
        row = cur.fetchone()
        if not row or row[1] == 1:
            return False

        conn.execute(
            """
            UPDATE bot_invites 
            SET is_used = 1, used_by = ?, used_at = CURRENT_TIMESTAMP 
            WHERE token = ?
        """,
            (telegram_id, token),
        )

        conn.execute(
            """
            INSERT INTO bot_users (telegram_id, username, full_name, role, is_active)
            VALUES (?, ?, ?, 'operator', 1)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                is_active = 1
        """,
            (telegram_id, username, full_name),
        )
        return True


def get_all_bot_users() -> List[Dict[str, Any]]:
    """Returns a list of all registered users."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT telegram_id, username, full_name, role, is_active, created_at FROM bot_users ORDER BY created_at ASC"
        )
        rows = cur.fetchall()
        return [
            {
                "telegram_id": r[0],
                "username": r[1],
                "full_name": r[2],
                "role": r[3],
                "is_active": bool(r[4]),
                "created_at": r[5],
            }
            for r in rows
        ]


# ================= DYNAMIC STORE & KNOWLEDGE BASE MANAGEMENT =================
def get_allowed_stores() -> Dict[str, str]:
    """Returns mapping of active store GUID to restaurant name."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT store_id, name FROM managed_stores WHERE is_active = 1")
        return {r[0]: r[1] for r in cur.fetchall()}


def get_all_managed_stores() -> List[Dict[str, Any]]:
    """Returns list of all stores registered in database."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT store_id, name, is_active FROM managed_stores ORDER BY name ASC")
        return [{"store_id": r[0], "name": r[1], "is_active": bool(r[2])} for r in cur.fetchall()]


def add_managed_store(store_id: str, name: str) -> None:
    """Adds or activates a restaurant store."""
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO managed_stores (store_id, name, is_active) VALUES (?, ?, 1)
            ON CONFLICT(store_id) DO UPDATE SET name = excluded.name, is_active = 1
        """,
            (store_id.strip(), name.strip()),
        )


def delete_managed_store(store_id: str) -> None:
    """Deletes a restaurant store from active managed list."""
    with get_db_connection() as conn:
        conn.execute("DELETE FROM managed_stores WHERE store_id = ?", (store_id.strip(),))


def search_mappings_for_admin(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Searches knowledge base mappings for inspection or deletion."""
    with get_db_connection() as conn:
        conn.create_function("lower", 1, lambda s: s.lower() if s else "")
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, raw_name, iiko_name, iiko_article, usage_count, package_coefficient
            FROM supplier_mappings
            WHERE LOWER(raw_name) LIKE ? OR LOWER(iiko_name) LIKE ? OR iiko_article LIKE ?
            ORDER BY usage_count DESC
            LIMIT ?
        """,
            (f"%{query.lower()}%", f"%{query.lower()}%", f"%{query}%", limit),
        )
        return [
            {
                "id": r[0],
                "raw_name": r[1],
                "iiko_name": r[2],
                "article": r[3],
                "usage_count": r[4],
                "coefficient": r[5],
            }
            for r in cur.fetchall()
        ]


def delete_mapping_by_id(mapping_id: int) -> bool:
    """Deletes an incorrect learned mapping from knowledge base."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM supplier_mappings WHERE id = ?", (mapping_id,))
        return cur.rowcount > 0


if __name__ == "__main__":
    init_db()
    print("[+] Database initialized successfully.")
