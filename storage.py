import sqlite3
from typing import Optional, List, Dict, Any, Tuple

DB_PATH = "iiko_matcher.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # 1. База знаний сопоставлений с историей и голосами
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
        
        # 2. Память выбора поставщиков (для дублей ИНН вроде Форвард Трейд)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS preferred_suppliers (
                inn TEXT PRIMARY KEY,
                supplier_id TEXT NOT NULL,
                supplier_name TEXT NOT NULL
            )
        """)

        # 3. Статистика использования ключей Gemini API
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

def record_mapping_vote(supplier_id: str, raw_name: str, product_id: str, iiko_name: str, article: str = "", weight: int = 1):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO supplier_mappings 
            (supplier_id, raw_name, product_id, iiko_name, iiko_article, usage_count, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(supplier_id, raw_name, product_id) 
            DO UPDATE SET 
                usage_count = usage_count + ?,
                last_used_at = CURRENT_TIMESTAMP
        """, (supplier_id, raw_name.strip(), product_id, iiko_name, article, weight, weight))

def get_consensus_mapping(supplier_id: str, raw_name: str) -> Optional[Dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT product_id, iiko_name, iiko_article, usage_count
            FROM supplier_mappings
            WHERE supplier_id = ? AND raw_name = ?
            ORDER BY usage_count DESC, last_used_at DESC
        """, (supplier_id, raw_name.strip()))
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
            "all_variants": rows
        }

def save_preferred_supplier(inn: str, supplier_id: str, supplier_name: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO preferred_suppliers (inn, supplier_id, supplier_name) VALUES (?, ?, ?)",
                     (inn, supplier_id, supplier_name))

def get_preferred_supplier(inn: str) -> Optional[Tuple[str, str]]:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT supplier_id, supplier_name FROM preferred_suppliers WHERE inn = ?", (inn,))
        return cur.fetchone()

def record_gemini_key_stat(key_name: str, success: bool, is_rate_limit: bool = False):
    """Records key usage metrics transactionally."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO gemini_key_stats (key_name, total_requests, successful_requests, rate_limit_hits, last_used_at)
            VALUES (?, 1, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key_name) DO UPDATE SET
                total_requests = total_requests + 1,
                successful_requests = successful_requests + ?,
                rate_limit_hits = rate_limit_hits + ?,
                last_used_at = CURRENT_TIMESTAMP
        """, (
            key_name,
            1 if success else 0,
            1 if is_rate_limit else 0,
            1 if success else 0,
            1 if is_rate_limit else 0
        ))

def get_gemini_key_usage_counts() -> Dict[str, int]:
    """Returns mapping of key_name to total number of requests."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT key_name, total_requests FROM gemini_key_stats")
        return dict(cur.fetchall())

def get_all_gemini_key_stats() -> List[Tuple[str, int, int, int, str]]:
    """Returns full reporting metrics for all tracked API keys."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT key_name, total_requests, successful_requests, rate_limit_hits, last_used_at
            FROM gemini_key_stats
            ORDER BY total_requests DESC
        """)
        return cur.fetchall()

if __name__ == "__main__":
    init_db()
    print("[+] БД инициализирована без лишних сущностей.")