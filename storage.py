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

if __name__ == "__main__":
    init_db()
    print("[+] БД инициализирована без лишних сущностей.")