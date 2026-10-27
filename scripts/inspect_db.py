#!/usr/bin/env python3
import sys
import sqlite3

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "state", "iiko_matcher.db")


def inspect(search_query: str = ""):
    conn = sqlite3.connect(DB_PATH)
    conn.create_function("lower", 1, lambda s: s.lower() if s else "")
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*), SUM(usage_count), COUNT(DISTINCT supplier_id) FROM supplier_mappings"
    )
    total_unique, total_votes, total_suppliers = cur.fetchone()

    print("=" * 80)
    print(f"📊 ITEM MAPPING KNOWLEDGE BASE STATS ({DB_PATH})")
    print(f"   Suppliers in database:        {total_suppliers or 0}")
    print(f"   Unique product pairs:         {total_unique or 0}")
    print(f"   Total confirmed votes:        {total_votes or 0}")
    print("=" * 80)

    # Check for ambiguous item mappings
    cur.execute("""
        SELECT supplier_id, raw_name, COUNT(DISTINCT product_id) as cnt
        FROM supplier_mappings
        GROUP BY supplier_id, raw_name
        HAVING cnt > 1
    """)
    conflicts = cur.fetchall()

    if conflicts:
        print(f"\n⚠️  AMBIGUOUS MAPPINGS DETECTED: {len(conflicts)}")
        for supp_id, raw_name, _ in conflicts[:5]:
            print(f"\n   Vendor Item Name: '{raw_name}'")
            cur.execute(
                """
                SELECT iiko_name, iiko_article, usage_count 
                FROM supplier_mappings 
                WHERE supplier_id = ? AND raw_name = ?
                ORDER BY usage_count DESC
            """,
                (supp_id, raw_name),
            )
            for row in cur.fetchall():
                print(f"     └─ selected {row[2]} time(s): '{row[0]}' (sku: {row[1]})")
        print("-" * 80)
    else:
        print("\n✨ ALL MAPPINGS ARE 100% UNAMBIGUOUS. Zero conflicts.")

    # Case-insensitive Unicode substring search
    if search_query:
        print(f"\n🔍 SEARCH RESULTS FOR QUERY: '{search_query}'")
        cur.execute(
            """
            SELECT raw_name, iiko_name, iiko_article, usage_count, package_coefficient
            FROM supplier_mappings
            WHERE LOWER(raw_name) LIKE ? OR LOWER(iiko_name) LIKE ? OR iiko_article LIKE ?
            ORDER BY usage_count DESC
        """,
            (
                f"%{search_query.lower()}%",
                f"%{search_query.lower()}%",
                f"%{search_query}%",
            ),
        )
    else:
        print("\n🏆 TOP-15 MOST FREQUENT MAPPINGS:")
        cur.execute("""
            SELECT raw_name, iiko_name, iiko_article, usage_count, package_coefficient
            FROM supplier_mappings
            ORDER BY usage_count DESC
            LIMIT 15
        """)

    rows = cur.fetchall()
    if not rows:
        print("   No records found.")
    else:
        print(
            f"{'VOTES':<8} | {'COEFF':<7} | {'INVOICE RAW NAME':<36} | {'IIKO PRODUCT NAME':<33}"
        )
        print("-" * 92)
        for r in rows:
            votes = f"x{r[3]}"
            coeff = f"x{r[4]:g}" if len(r) > 4 and r[4] and r[4] > 1.0 else "1.0"
            raw = r[0][:34]
            iiko = f"{r[1]} ({r[2]})" if r[2] else r[1]
            print(f"{votes:<8} | {coeff:<7} | {raw:<36} | {iiko[:33]:<33}")
    print("=" * 92)

    # 4. Gemini key rotation telemetry
    from storage import get_all_gemini_key_stats

    gemini_stats = get_all_gemini_key_stats()
    if gemini_stats:
        print("\n🔑 GEMINI API KEY ROTATION TELEMETRY:")
        print(
            f"{'ACCOUNT':<20} | {'TOTAL':<8} | {'SUCCESS':<8} | {'429 LIMIT':<10} | {'LAST REQUEST'}"
        )
        print("-" * 75)
        for g_row in gemini_stats:
            print(
                f"{g_row[0]:<20} | {g_row[1]:<8} | {g_row[2]:<8} | {g_row[3]:<10} | {g_row[4]}"
            )
        print("=" * 75)


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    inspect(query)
