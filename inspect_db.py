#!/usr/bin/env python3
import sys
import sqlite3

DB_PATH = "iiko_matcher.db"

def inspect(search_query: str = ""):
    conn = sqlite3.connect(DB_PATH)
    conn.create_function("lower", 1, lambda s: s.lower() if s else "")
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*), SUM(usage_count), COUNT(DISTINCT supplier_id) FROM supplier_mappings")
    total_unique, total_votes, total_suppliers = cur.fetchone()
    
    print("=" * 80)
    print(f"📊 СТАТИСТИКА БАЗЫ СОПОСТАВЛЕНИЙ ({DB_PATH})")
    print(f"   Поставщиков в базе:          {total_suppliers or 0}")
    print(f"   Уникальных пар (связок):     {total_unique or 0}")
    print(f"   Всего подтверждений/голосов: {total_votes or 0}")
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
        print(f"\n⚠️  НАЙДЕНО СПОРНЫХ ПОЗИЦИЙ: {len(conflicts)}")
        for supp_id, raw_name, _ in conflicts[:5]:
            print(f"\n   Позиция поставщика: '{raw_name}'")
            cur.execute("""
                SELECT iiko_name, iiko_article, usage_count 
                FROM supplier_mappings 
                WHERE supplier_id = ? AND raw_name = ?
                ORDER BY usage_count DESC
            """, (supp_id, raw_name))
            for row in cur.fetchall():
                print(f"     └─ {row[2]} раз(а) выбрано: '{row[0]}' (арт. {row[1]})")
        print("-" * 80)
    else:
        print("\n✨ ВСЕ СВЯЗКИ 100% ОДНОЗНАЧНЫ! Конфликтов нет.")

    # Case-insensitive Unicode substring search
    if search_query:
        print(f"\n🔍 РЕЗУЛЬТАТЫ ПОИСКА ПО ЗАПРОСУ: '{search_query}'")
        cur.execute("""
            SELECT raw_name, iiko_name, iiko_article, usage_count
            FROM supplier_mappings
            WHERE LOWER(raw_name) LIKE ? OR LOWER(iiko_name) LIKE ? OR iiko_article LIKE ?
            ORDER BY usage_count DESC
        """, (f"%{search_query.lower()}%", f"%{search_query.lower()}%", f"%{search_query}%"))
    else:
        print("\n🏆 ТОП-15 САМЫХ ЧАСТО ПРОВОДИМЫХ ПОЗИЦИЙ:")
        cur.execute("""
            SELECT raw_name, iiko_name, iiko_article, usage_count
            FROM supplier_mappings
            ORDER BY usage_count DESC
            LIMIT 15
        """)

    rows = cur.fetchall()
    if not rows:
        print("   Ничего не найдено.")
    else:
        print(f"{'ГОЛОСА':<8} | {'ИЗ НАКЛАДНОЙ':<40} | {'ТОВАР В IIKO':<35}")
        print("-" * 88)
        for r in rows:
            votes = f"x{r[3]}"
            raw = r[0][:38]
            iiko = f"{r[1]} ({r[2]})" if r[2] else r[1]
            print(f"{votes:<8} | {raw:<40} | {iiko[:35]:<35}")
    print("=" * 88)

    # 4. Gemini key rotation telemetry
    from storage import get_all_gemini_key_stats
    gemini_stats = get_all_gemini_key_stats()
    if gemini_stats:
        print("\n🔑 СТАТИСТИКА РОТАЦИИ КЛЮЧЕЙ GEMINI API:")
        print(f"{'АККАУНТ':<20} | {'ВСЕГО':<8} | {'УСПЕХ':<8} | {'429 ЛИМИТ':<10} | {'ПОСЛЕДНИЙ ЗАПРОС'}")
        print("-" * 75)
        for g_row in gemini_stats:
            print(f"{g_row[0]:<20} | {g_row[1]:<8} | {g_row[2]:<8} | {g_row[3]:<10} | {g_row[4]}")
        print("=" * 75)

if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    inspect(query)