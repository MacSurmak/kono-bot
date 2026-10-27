#!/usr/bin/env python3
import os
import sys
import json
import argparse
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
from collections import Counter

import asyncio

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers import parse_document
from services.iiko_client import client
from storage import init_db, close_db, record_mapping_vote


async def train_async(data_dir: str, override_from: str = None, override_to: str = None):
    await init_db()
    if not os.path.exists(data_dir):
        print(f"[-] Directory '{data_dir}' not found!")
        sys.exit(1)

    supported_exts = (".xml", ".pdf")
    files = [
        os.path.join(data_dir, f)
        for f in os.listdir(data_dir)
        if f.lower().endswith(supported_exts)
    ]

    if not files:
        print(f"[-] No supported files (.xml, .pdf) found in '{data_dir}'!")
        return

    print(f"[*] Scanning {len(files)} files in '{data_dir}'...")

    # 1. Parse all documents into memory and calculate date boundaries
    parsed_docs = []
    valid_dates = []

    for file_path in files:
        try:
            doc = parse_document(file_path)
            if doc and doc.items:
                parsed_docs.append(doc)
                try:
                    d_obj = datetime.strptime(doc.doc_date, "%Y-%m-%d").date()
                    valid_dates.append(d_obj)
                except ValueError as ve:
                    print(
                        f"[-] [Date Warning] Invalid date '{doc.doc_date}' in {os.path.basename(file_path)}: {ve}"
                    )
        except Exception as e:
            print(
                f"[-] [Parse Error] Failed to parse {os.path.basename(file_path)}: {e}"
            )

    if not parsed_docs:
        print("[-] Failed to parse any document in directory.")
        return

    print(f"[+] Successfully parsed documents: {len(parsed_docs)} of {len(files)}")

    # 2. Dynamic date range calculation with +/- 5-day boundary buffer
    if valid_dates:
        min_doc_date = min(valid_dates)
        max_doc_date = max(valid_dates)

        auto_from = (min_doc_date - timedelta(days=5)).strftime("%Y-%m-%d")
        auto_to = (max_doc_date + timedelta(days=5)).strftime("%Y-%m-%d")

        print(f"    Document date span: from {min_doc_date} to {max_doc_date}")
    else:
        auto_from = "2026-01-01"
        auto_to = "2026-12-31"

    date_from = override_from or auto_from
    date_to = override_to or auto_to

    print(f"    iiko query window: {date_from} to {date_to} (automated with buffer)")

    # 3. Load active inventory pool excluding archive and delivery menus
    print("\n[*] Loading active catalog and verifying folders...")
    active_products = client.get_active_stock_products()
    active_pool = {p["id"]: p for p in active_products}
    print(
        f"[+] Active inventory pool: {len(active_pool)} (archive and delivery excluded)"
    )

    # 4. Fetch historical invoices and suppliers from iiko
    print(f"[*] Querying historical invoices and supplier registry from iiko...")
    suppliers_grouped = client.get_suppliers_grouped()

    inv_resp = client.get(
        "/api/documents/export/incomingInvoice",
        params={"from": date_from, "to": date_to},
    )
    inv_root = ET.fromstring(inv_resp.content)
    iiko_docs = inv_root.findall(".//document")
    print(f"[+] Invoices found in iiko for this period: {len(iiko_docs)}")

    # Index iiko invoices strictly by supplier to prevent cross-vendor namespace collisions
    iiko_by_supp_and_num = {}
    iiko_by_supp_and_sum = {}

    for d in iiko_docs:
        s_id = (d.findtext("supplier") or "").strip()
        inc_num = (d.findtext("incomingDocumentNumber") or "").strip()
        items = d.findall(".//items/item")
        doc_sum = round(sum(float(it.findtext("sum", 0)) for it in items), 2)

        if s_id and inc_num:
            iiko_by_supp_and_num[(s_id, inc_num)] = d
        if s_id and doc_sum > 0:
            iiko_by_supp_and_sum.setdefault((s_id, doc_sum), []).append(d)

    # 5. Deterministic alignment engine with full diagnostic telemetry
    print("\n[*] Starting Deterministic Training Engine (Strict Invariants)...")

    sequential_invoices = 0
    unique_sum_invoices = 0
    learned_items_count = 0

    successful_logs = []
    unmatched_diagnostics = []

    for doc in parsed_docs:
        target_num = doc.doc_number
        target_sum = round(sum(it.sum for it in doc.items), 2)
        filename = os.path.basename(doc.source_file)

        valid_supps = suppliers_grouped.get(doc.supplier_inn, [])
        valid_supplier_ids = {s["id"] for s in valid_supps}

        # Check 1: Supplier existence in iiko registry
        if not valid_supplier_ids:
            unmatched_diagnostics.append(
                {
                    "file": filename,
                    "doc_number": target_num,
                    "doc_date": doc.doc_date,
                    "supplier_name": doc.supplier_name,
                    "supplier_inn": doc.supplier_inn,
                    "total_sum": target_sum,
                    "items_count": len(doc.items),
                    "category": "SUPPLIER_NOT_IN_IIKO",
                    "diagnosis": f"Supplier INN '{doc.supplier_inn}' ({doc.supplier_name}) not registered in iiko",
                    "lines": [],
                }
            )
            continue

        # Check 2: Match iiko document by supplier + number or unique sum
        matched_iiko_doc = None
        for s_id in valid_supplier_ids:
            if (s_id, target_num) in iiko_by_supp_and_num:
                matched_iiko_doc = iiko_by_supp_and_num[(s_id, target_num)]
                break

        if matched_iiko_doc is None:
            for s_id in valid_supplier_ids:
                candidates = iiko_by_supp_and_sum.get((s_id, target_sum), [])
                if len(candidates) == 1:
                    matched_iiko_doc = candidates[0]
                    break

        if matched_iiko_doc is None:
            other_supp = None
            for (s_id, inc_num), d in iiko_by_supp_and_num.items():
                if inc_num.strip().lower() == target_num.strip().lower():
                    other_supp = s_id
                    break

            if other_supp:
                category = "SUPPLIER_MISMATCH"
                diagnosis = f"Invoice #{target_num} exists in iiko, but belongs to another supplier (ID: {other_supp})"
            else:
                category = "NOT_FOUND_IN_IIKO"
                diagnosis = f"Invoice #{target_num} with total sum {target_sum:.2f} RUB not found in iiko window ({date_from}..{date_to})"

            unmatched_diagnostics.append(
                {
                    "file": filename,
                    "doc_number": target_num,
                    "doc_date": doc.doc_date,
                    "supplier_name": doc.supplier_name,
                    "supplier_inn": doc.supplier_inn,
                    "total_sum": target_sum,
                    "items_count": len(doc.items),
                    "category": category,
                    "diagnosis": diagnosis,
                    "lines": [],
                }
            )
            continue

        supplier_id = matched_iiko_doc.findtext("supplier")
        iiko_num = matched_iiko_doc.findtext("documentNumber") or "UNKNOWN"
        raw_iiko_items = matched_iiko_doc.findall(".//items/item")

        # Check 3: Verify active stock products
        iiko_items = []
        inactive_names = []
        for it in raw_iiko_items:
            p_id = it.findtext("product")
            if p_id not in active_pool:
                inactive_names.append(f"Product {p_id}")
            else:
                iiko_items.append(
                    {
                        "product_id": p_id,
                        "name": active_pool[p_id]["name"],
                        "article": active_pool[p_id]["article"],
                        "amount": float(it.findtext("amount", 0)),
                        "sum": round(float(it.findtext("sum", 0)), 2),
                    }
                )

        if inactive_names:
            unmatched_diagnostics.append(
                {
                    "file": filename,
                    "doc_number": target_num,
                    "doc_date": doc.doc_date,
                    "supplier_name": doc.supplier_name,
                    "supplier_inn": doc.supplier_inn,
                    "total_sum": target_sum,
                    "items_count": len(doc.items),
                    "iiko_internal_num": iiko_num,
                    "category": "ARCHIVED_ITEM_PRESENT",
                    "diagnosis": f"iiko invoice #{iiko_num} contains {len(inactive_names)} archived/inactive item(s): {', '.join(inactive_names[:3])}",
                    "lines": [],
                }
            )
            continue

        # Check 4: Line count discrepancy
        if len(doc.items) != len(iiko_items):
            lines_detail = []
            for d_idx, d_it in enumerate(doc.items, 1):
                lines_detail.append(
                    f"  [Diadoc {d_idx:02d}] {d_it.raw_name[:36]:<36} | {d_it.quantity:>6.2f} qty | {d_it.sum:>9.2f} RUB"
                )
            for i_idx, i_it in enumerate(iiko_items, 1):
                lines_detail.append(
                    f"  [iiko   {i_idx:02d}] {i_it['name'][:36]:<36} | {i_it['amount']:>6.2f} qty | {i_it['sum']:>9.2f} RUB"
                )

            unmatched_diagnostics.append(
                {
                    "file": filename,
                    "doc_number": target_num,
                    "doc_date": doc.doc_date,
                    "supplier_name": doc.supplier_name,
                    "supplier_inn": doc.supplier_inn,
                    "total_sum": target_sum,
                    "items_count": len(doc.items),
                    "iiko_internal_num": iiko_num,
                    "category": "LINE_COUNT_MISMATCH",
                    "diagnosis": f"Line count mismatch: Diadoc has {len(doc.items)} lines, iiko has {len(iiko_items)} lines (Diadoc={target_sum:.2f} RUB, iiko={sum(it['sum'] for it in iiko_items):.2f} RUB)",
                    "lines": lines_detail,
                }
            )
            continue

        # Check 5: Strict sequential order with packaging coefficient calculation
        is_sequential = True
        temp_seq = []
        for d_item, i_item in zip(doc.items, iiko_items):
            d_sum = round(d_item.sum, 2)
            if abs(d_sum - i_item["sum"]) >= 0.50:
                is_sequential = False
                break

            # Calculate packaging multiplier (integer packs, metric 0.001, or fractional)
            d_qty = d_item.quantity
            i_amount = i_item["amount"]
            coeff = 1.0
            if d_qty > 0 and i_amount > 0:
                ratio = i_amount / d_qty
                if abs(ratio - round(ratio)) < 0.01 and round(ratio) >= 1:
                    coeff = float(round(ratio))
                elif abs(ratio - 0.001) < 0.00001:
                    coeff = 0.001
                elif abs(ratio - 0.01) < 0.0001:
                    coeff = 0.01
                elif abs(ratio - 0.1) < 0.001:
                    coeff = 0.1
                elif abs(ratio - 0.5) < 0.001:
                    coeff = 0.5
                elif abs(ratio - 0.25) < 0.001:
                    coeff = 0.25
                elif abs(ratio * 10 - round(ratio * 10)) < 0.01:
                    coeff = round(ratio, 2)
                else:
                    coeff = round(ratio, 4)

            temp_seq.append(
                {
                    "supplier_id": supplier_id,
                    "raw_name": d_item.raw_name,
                    "product_id": i_item["product_id"],
                    "iiko_name": i_item["name"],
                    "article": d_item.article or i_item["article"],
                    "package_coefficient": coeff,
                }
            )

        if is_sequential:
            sequential_invoices += 1
            for pair in temp_seq:
                await record_mapping_vote(
                    supplier_id=pair["supplier_id"],
                    raw_name=pair["raw_name"],
                    product_id=pair["product_id"],
                    iiko_name=pair["iiko_name"],
                    article=pair["article"],
                    weight=1,
                    package_coefficient=pair["package_coefficient"],
                    source="cli_train",
                )
                learned_items_count += 1

            successful_logs.append(
                {
                    "file": filename,
                    "doc_number": target_num,
                    "doc_date": doc.doc_date,
                    "supplier_name": doc.supplier_name,
                    "total_sum": target_sum,
                    "matched_count": len(temp_seq),
                    "mode": "STRICT_ORDER",
                }
            )
            print(
                f"[✅ STRICT ORDER] {filename:<28} | Doc: {target_num:<10} | Sum: {target_sum:>9.2f} ({len(temp_seq)} items)"
            )
            continue

        # Check 6: Unique-sum permutation bijections
        d_sums = Counter(round(it.sum, 2) for it in doc.items)
        i_sums = Counter(it["sum"] for it in iiko_items)

        unique_sums = {
            s for s, count in d_sums.items() if count == 1 and i_sums.get(s) == 1
        }

        if unique_sums:
            doc_by_sum = {round(it.sum, 2): it for it in doc.items}
            iiko_by_sum_row = {it["sum"]: it for it in iiko_items}

            stage2_pairs = []
            for s in unique_sums:
                d_it = doc_by_sum[s]
                i_it = iiko_by_sum_row[s]

                d_qty = d_it.quantity
                i_amount = i_it["amount"]
                coeff = 1.0
                if d_qty > 0 and i_amount > 0:
                    ratio = i_amount / d_qty
                    if abs(ratio - round(ratio)) < 0.01 and round(ratio) >= 1:
                        coeff = float(round(ratio))
                    elif abs(ratio - 0.001) < 0.00001:
                        coeff = 0.001
                    elif abs(ratio - 0.01) < 0.0001:
                        coeff = 0.01
                    elif abs(ratio - 0.1) < 0.001:
                        coeff = 0.1
                    elif abs(ratio - 0.5) < 0.001:
                        coeff = 0.5
                    elif abs(ratio - 0.25) < 0.001:
                        coeff = 0.25
                    elif abs(ratio * 10 - round(ratio * 10)) < 0.01:
                        coeff = round(ratio, 2)
                    else:
                        coeff = round(ratio, 4)

                stage2_pairs.append(
                    {
                        "supplier_id": supplier_id,
                        "raw_name": d_it.raw_name,
                        "product_id": i_it["product_id"],
                        "iiko_name": i_it["name"],
                        "article": d_it.article or i_it["article"],
                        "package_coefficient": coeff,
                    }
                )

            if stage2_pairs:
                unique_sum_invoices += 1
                for pair in stage2_pairs:
                    await record_mapping_vote(
                        supplier_id=pair["supplier_id"],
                        raw_name=pair["raw_name"],
                        product_id=pair["product_id"],
                        iiko_name=pair["iiko_name"],
                        article=pair["article"],
                        weight=1,
                        package_coefficient=pair["package_coefficient"],
                        source="cli_train",
                    )
                    learned_items_count += 1

                successful_logs.append(
                    {
                        "file": filename,
                        "doc_number": target_num,
                        "doc_date": doc.doc_date,
                        "supplier_name": doc.supplier_name,
                        "total_sum": target_sum,
                        "matched_count": len(stage2_pairs),
                        "mode": "UNIQUE_SUMS",
                    }
                )
                print(
                    f"[🎯 UNIQUE SUMS]  {filename:<28} | Doc: {target_num:<10} | Sum: {target_sum:>9.2f} (Matched {len(stage2_pairs)} items)"
                )

                # If partial matches occurred, log the remaining duplicate rows for audit
                if len(stage2_pairs) < len(doc.items):
                    skipped_sums = [s for s, cnt in d_sums.items() if cnt > 1]
                    unmatched_diagnostics.append(
                        {
                            "file": filename,
                            "doc_number": target_num,
                            "doc_date": doc.doc_date,
                            "supplier_name": doc.supplier_name,
                            "supplier_inn": doc.supplier_inn,
                            "total_sum": target_sum,
                            "items_count": len(doc.items),
                            "iiko_internal_num": iiko_num,
                            "category": "PARTIAL_MATCH_DUPLICATE_PRICES",
                            "diagnosis": f"Matched {len(stage2_pairs)} of {len(doc.items)} lines via unique sums. Remaining lines skipped due to duplicate prices: {skipped_sums[:4]}",
                            "lines": [],
                        }
                    )
                continue

        # Disordered rows with duplicate prices
        duplicate_price_list = [
            f"{s:.2f} RUB (x{cnt})" for s, cnt in d_sums.items() if cnt > 1
        ]
        lines_detail = [
            f"  [Diadoc] {it.raw_name[:36]:<36} | {it.sum:>9.2f} RUB"
            for it in doc.items
        ]
        unmatched_diagnostics.append(
            {
                "file": filename,
                "doc_number": target_num,
                "doc_date": doc.doc_date,
                "supplier_name": doc.supplier_name,
                "supplier_inn": doc.supplier_inn,
                "total_sum": target_sum,
                "items_count": len(doc.items),
                "iiko_internal_num": iiko_num,
                "category": "AMBIGUOUS_DUPLICATE_PRICES",
                "diagnosis": f"Row order is permuted and contains duplicate line sums ({', '.join(duplicate_price_list[:3])}). Skipped to prevent flavour/item mixups.",
                "lines": lines_detail,
            }
        )

    # 6. Save persistent diagnostic artifacts
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "out")
    os.makedirs(out_dir, exist_ok=True)

    unmatched_txt_path = os.path.join(out_dir, "training_unmatched.txt")
    success_txt_path = os.path.join(out_dir, "training_success.txt")
    telemetry_json_path = os.path.join(out_dir, "training_telemetry.json")

    # Write human-readable unmatched diagnosis
    with open(unmatched_txt_path, "w", encoding="utf-8") as f:
        f.write("=" * 105 + "\n")
        f.write(
            "📊 ОТЧЕТ О НЕСОПОСТАВЛЕННЫХ НАКЛАДНЫХ ПРИ ОБУЧЕНИИ (ДЕТАЛЬНАЯ ДИАГНОСТИКА)\n"
        )
        f.write("=" * 105 + "\n\n")
        for d in unmatched_diagnostics:
            iiko_info = (
                f" (iiko #{d['iiko_internal_num']})"
                if d.get("iiko_internal_num")
                else ""
            )
            f.write("=" * 105 + "\n")
            f.write(
                f"❌ НАКЛАДНАЯ: № {d['doc_number']} от {d['doc_date']}{iiko_info} | Сумма: {d['total_sum']:,.2f} ₽ | Строк: {d['items_count']}\n"
            )
            f.write(f"   Файл:      {d['file']}\n")
            f.write(f"   Поставщик: {d['supplier_name']} (ИНН: {d['supplier_inn']})\n")
            f.write(f"   ДИАГНОЗ:   {d['category']}\n")
            f.write(f"   Причина:   {d['diagnosis']}\n")
            if d.get("lines"):
                f.write("   " + "-" * 100 + "\n")
                f.write("   Детализация строк:\n")
                for line in d["lines"]:
                    f.write(f"   {line}\n")
            f.write("=" * 105 + "\n\n")

    # Write human-readable success journal
    with open(success_txt_path, "w", encoding="utf-8") as f:
        f.write("=" * 105 + "\n")
        f.write("✅ ЖУРНАЛ УСПЕШНО СОПОСТАВЛЕННЫХ НАКЛАДНЫХ ПРИ ОБУЧЕНИИ\n")
        f.write("=" * 105 + "\n\n")
        for s in successful_logs:
            f.write(
                f"[{s['mode']:<12}] № {s['doc_number']:<14} | {s['doc_date']} | {s['total_sum']:>10.2f} ₽ | Выучено: {s['matched_count']:>2} поз. | {s['supplier_name'][:30]:<30} ({s['file']})\n"
            )

    # Write structured JSON telemetry
    with open(telemetry_json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(),
                "summary": {
                    "total_documents": len(parsed_docs),
                    "strict_order": sequential_invoices,
                    "unique_sums": unique_sum_invoices,
                    "utilized_invoices": sequential_invoices + unique_sum_invoices,
                    "learned_items_count": learned_items_count,
                    "unmatched_count": len(unmatched_diagnostics),
                },
                "unmatched": unmatched_diagnostics,
                "matched": successful_logs,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    # Calculate categories stats
    diag_counts = Counter(d["category"] for d in unmatched_diagnostics)

    # Print final summary
    print("\n" + "=" * 75)
    print("📊 [DETERMINISTIC TRAINING SUMMARY]")
    print(f"  Processed documents:                {len(parsed_docs)}")
    print(f"  Matched via strict order:           {sequential_invoices}")
    print(f"  Matched via unique sum bijections:  {unique_sum_invoices}")
    print(
        f"  TOTAL INVOICES UTILIZED:            {sequential_invoices + unique_sum_invoices} of {len(parsed_docs)}"
    )
    print(f"  TOTAL VERIFIED MAPPINGS IN DB:      {learned_items_count}")
    print("-" * 75)
    print("🔎 [СТАТИСТИКА НЕСОПОСТАВЛЕННЫХ НАКЛАДНЫХ ПО ДИАГНОЗАМ]:")
    for cat, cnt in diag_counts.most_common():
        print(f"  • {cat:<32}: {cnt} шт.")
    print("=" * 75)
    print(f"[+] Человекочитаемый отчет по ошибкам: {unmatched_txt_path}")
    print(f"[+] Журнал успешных накладных:         {success_txt_path}")
    print(f"[+] Машиночитаемая JSON-телеметрия:    {telemetry_json_path}")
    print("=" * 75 + "\n")
    await close_db()


def train(data_dir: str, override_from: str = None, override_to: str = None):
    asyncio.run(train_async(data_dir, override_from, override_to))


def main():
    parser = argparse.ArgumentParser(
        description="Automated multi-pass training for iiko item matcher"
    )
    parser.add_argument(
        "--dir",
        default="data/in/diadoc_xmls",
        help="Directory with invoice files (default: data/in/diadoc_xmls)",
    )
    parser.add_argument(
        "--from-date",
        dest="override_from",
        default=None,
        help="Explicit start date YYYY-MM-DD",
    )
    parser.add_argument(
        "--to-date",
        dest="override_to",
        default=None,
        help="Explicit end date YYYY-MM-DD",
    )
    args = parser.parse_args()

    train(args.dir, args.override_from, args.override_to)


if __name__ == "__main__":
    main()
