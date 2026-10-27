#!/usr/bin/env python3
import os
import sys
import asyncio

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage import init_db, close_db, get_db_pool


async def inspect_async(search_query: str = ""):
    await init_db()
    pool = get_db_pool()

    row = await pool.fetchrow(
        "SELECT COUNT(*), COALESCE(SUM(usage_count), 0), COUNT(DISTINCT supplier_id) FROM supplier_mappings;"
    )
    total_unique, total_votes, total_suppliers = row[0], row[1], row[2]

    host = os.getenv("POSTGRES_HOST", "localhost")
    db = os.getenv("POSTGRES_DB", "kono_supply")
    print("=" * 80)
    print(f"📊 ITEM MAPPING KNOWLEDGE BASE STATS (PostgreSQL: {host}/{db})")
    print(f"   Suppliers in database:        {total_suppliers or 0}")
    print(f"   Unique product pairs:         {total_unique or 0}")
    print(f"   Total confirmed votes:        {total_votes or 0}")
    print("=" * 80)

    # Check for ambiguous item mappings
    conflicts = await pool.fetch("""
        SELECT supplier_id, raw_name, COUNT(DISTINCT product_id) as cnt
        FROM supplier_mappings
        GROUP BY supplier_id, raw_name
        HAVING COUNT(DISTINCT product_id) > 1;
    """)

    if conflicts:
        print(f"\n⚠️  AMBIGUOUS MAPPINGS DETECTED: {len(conflicts)}")
        for supp_id, raw_name, _ in conflicts[:5]:
            print(f"\n   Vendor Item Name: '{raw_name}'")
            variants = await pool.fetch(
                """
                SELECT iiko_name, iiko_article, usage_count 
                FROM supplier_mappings 
                WHERE supplier_id = $1 AND raw_name = $2
                ORDER BY usage_count DESC;
            """,
                supp_id,
                raw_name,
            )
            for row in variants:
                print(f"     └─ selected {row['usage_count']} time(s): '{row['iiko_name']}' (sku: {row['iiko_article']})")
        print("-" * 80)
    else:
        print("\n✨ ALL MAPPINGS ARE 100% UNAMBIGUOUS. Zero conflicts.")

    # Case-insensitive substring search
    if search_query:
        print(f"\n🔍 SEARCH RESULTS FOR QUERY: '{search_query}'")
        like_pattern = f"%{search_query.lower()}%"
        rows = await pool.fetch(
            """
            SELECT raw_name, iiko_name, iiko_article, usage_count, package_coefficient
            FROM supplier_mappings
            WHERE LOWER(raw_name) LIKE $1 OR LOWER(iiko_name) LIKE $1 OR LOWER(COALESCE(iiko_article, '')) LIKE $1
            ORDER BY usage_count DESC;
        """,
            like_pattern,
        )
    else:
        print("\n🏆 TOP-15 MOST FREQUENT MAPPINGS:")
        rows = await pool.fetch("""
            SELECT raw_name, iiko_name, iiko_article, usage_count, package_coefficient
            FROM supplier_mappings
            ORDER BY usage_count DESC
            LIMIT 15;
        """)
    if not rows:
        print("   No records found.")
    else:
        print(
            f"{'VOTES':<8} | {'COEFF':<7} | {'INVOICE RAW NAME':<36} | {'IIKO PRODUCT NAME':<33}"
        )
        print("-" * 92)
        for r in rows:
            votes = f"x{r['usage_count']}"
            coeff_val = float(r['package_coefficient']) if r['package_coefficient'] else 1.0
            coeff = f"x{coeff_val:g}" if coeff_val != 1.0 else "1.0"
            raw = r['raw_name'][:34]
            article_str = f" ({r['iiko_article']})" if r['iiko_article'] else ""
            iiko = f"{r['iiko_name']}{article_str}"
            print(f"{votes:<8} | {coeff:<7} | {raw:<36} | {iiko[:33]:<33}")
    print("=" * 92)

    # Gemini key rotation telemetry
    from storage import get_all_gemini_key_stats

    gemini_stats = await get_all_gemini_key_stats()
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


    await close_db()


def inspect(search_query: str = ""):
    asyncio.run(inspect_async(search_query))


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    inspect(query)
