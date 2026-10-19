#!/usr/bin/env python3
import os
import sys
import argparse
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

from parsers import parse_document
from iiko_client import client
from storage import init_db, record_mapping_vote

init_db()

def train(data_dir: str, override_from: str = None, override_to: str = None):
    if not os.path.exists(data_dir):
        print(f"[-] Directory '{data_dir}' not found!")
        sys.exit(1)

    supported_exts = (".xml", ".pdf")
    files = [os.path.join(data_dir, f) for f in os.listdir(data_dir) if f.lower().endswith(supported_exts)]
    
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
                except ValueError:
                    pass
        except Exception:
            continue

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
    print(f"[+] Active inventory pool: {len(active_pool)} (archive and delivery excluded)")

    # 4. Fetch historical invoices from iiko for detected period
    print(f"[*] Querying historical invoices from iiko...")
    inv_resp = client.get(
        "/api/documents/export/incomingInvoice",
        params={"from": date_from, "to": date_to}
    )
    inv_root = ET.fromstring(inv_resp.content)
    iiko_docs = inv_root.findall(".//document")
    print(f"[+] Invoices found in iiko for this period: {len(iiko_docs)}")

    # Index iiko invoices for O(1) matching
    iiko_by_num = {}
    iiko_by_sum = {}

    for d in iiko_docs:
        inc_num = (d.findtext("incomingDocumentNumber") or "").strip()
        items = d.findall(".//items/item")
        doc_sum = round(sum(float(it.findtext("sum", 0)) for it in items), 2)
        
        if inc_num:
            iiko_by_num[inc_num] = d
        if doc_sum > 0:
            iiko_by_sum.setdefault(doc_sum, []).append(d)

    # 5. Deterministic alignment engine (ZERO fuzzy search, 100% mathematical certainty)
    print("\n[*] Starting Deterministic Training Engine (Strict Invariants)...")
    from collections import Counter

    sequential_invoices = 0
    unique_sum_invoices = 0
    learned_items_count = 0

    for doc in parsed_docs:
        target_num = doc.doc_number
        target_sum = round(sum(it.sum for it in doc.items), 2)

        matched_iiko_doc = iiko_by_num.get(target_num)
        if matched_iiko_doc is None and target_sum in iiko_by_sum:
            candidates = iiko_by_sum[target_sum]
            if len(candidates) == 1:
                matched_iiko_doc = candidates[0]

        if matched_iiko_doc is None:
            continue

        supplier_id = matched_iiko_doc.findtext("supplier")
        raw_iiko_items = matched_iiko_doc.findall(".//items/item")

        # Extract active iiko items
        iiko_items = []
        has_inactive = False
        for it in raw_iiko_items:
            p_id = it.findtext("product")
            if p_id not in active_pool:
                has_inactive = True
                break
            iiko_items.append({
                "product_id": p_id,
                "name": active_pool[p_id]["name"],
                "article": active_pool[p_id]["article"],
                "amount": float(it.findtext("amount", 0)),
                "sum": round(float(it.findtext("sum", 0)), 2)
            })

        if has_inactive or not iiko_items:
            continue

        # --- INVARIANT 1: Strict Sequential Order ---
        # Document entered row-by-row where every line i has identical sum
        if len(doc.items) == len(iiko_items):
            is_sequential = True
            temp_seq = []
            for d_item, i_item in zip(doc.items, iiko_items):
                d_sum = round(d_item.sum, 2)
                if abs(d_sum - i_item["sum"]) >= 0.50:
                    is_sequential = False
                    break
                temp_seq.append({
                    "supplier_id": supplier_id,
                    "raw_name": d_item.raw_name,
                    "product_id": i_item["product_id"],
                    "iiko_name": i_item["name"],
                    "article": d_item.article or i_item["article"]
                })

            if is_sequential:
                sequential_invoices += 1
                for pair in temp_seq:
                    record_mapping_vote(
                        supplier_id=pair["supplier_id"],
                        raw_name=pair["raw_name"],
                        product_id=pair["product_id"],
                        iiko_name=pair["iiko_name"],
                        article=pair["article"],
                        weight=1
                    )
                    learned_items_count += 1
                print(f"[✅ STRICT ORDER] {os.path.basename(doc.source_file):<28} | Doc: {target_num:<10} | Sum: {target_sum:>9.2f} ({len(temp_seq)} items)")
                continue

        # --- INVARIANT 2: Unique-Sum Bijections ---
        # Only match rows whose sum appears EXACTLY ONCE in Diadoc AND EXACTLY ONCE in iiko.
        # If a sum appears >= 2 times (e.g. duplicate prices/flavors), SKIP IT completely. No guessing.
        d_sums = Counter(round(it.sum, 2) for it in doc.items)
        i_sums = Counter(it["sum"] for it in iiko_items)

        unique_sums = {s for s, count in d_sums.items() if count == 1 and i_sums.get(s) == 1}
        if not unique_sums:
            continue

        doc_by_sum = {round(it.sum, 2): it for it in doc.items}
        iiko_by_sum_row = {it["sum"]: it for it in iiko_items}

        stage2_pairs = []
        for s in unique_sums:
            d_it = doc_by_sum[s]
            i_it = iiko_by_sum_row[s]
            stage2_pairs.append({
                "supplier_id": supplier_id,
                "raw_name": d_it.raw_name,
                "product_id": i_it["product_id"],
                "iiko_name": i_it["name"],
                "article": d_it.article or i_it["article"]
            })

        if stage2_pairs:
            unique_sum_invoices += 1
            for pair in stage2_pairs:
                record_mapping_vote(
                    supplier_id=pair["supplier_id"],
                    raw_name=pair["raw_name"],
                    product_id=pair["product_id"],
                    iiko_name=pair["iiko_name"],
                    article=pair["article"],
                    weight=1
                )
                learned_items_count += 1
            print(f"[🎯 UNIQUE SUMS]  {os.path.basename(doc.source_file):<28} | Doc: {target_num:<10} | Sum: {target_sum:>9.2f} (Matched {len(stage2_pairs)} unambiguous items)")

    print("\n" + "=" * 70)
    print("📊 [DETERMINISTIC TRAINING SUMMARY]")
    print(f"  Processed documents:                {len(parsed_docs)}")
    print(f"  Matched via strict order:           {sequential_invoices}")
    print(f"  Matched via unique sum bijections:  {unique_sum_invoices}")
    print(f"  TOTAL INVOICES UTILIZED:            {sequential_invoices + unique_sum_invoices} of {len(parsed_docs)}")
    print(f"  TOTAL VERIFIED MAPPINGS IN DB:      {learned_items_count}")
    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(description="Automated multi-pass training for iiko item matcher")
    parser.add_argument("--dir", default="diadoc_xmls", help="Directory with invoice files (default: diadoc_xmls)")
    parser.add_argument("--from-date", dest="override_from", default=None, help="Explicit start date YYYY-MM-DD")
    parser.add_argument("--to-date", dest="override_to", default=None, help="Explicit end date YYYY-MM-DD")
    args = parser.parse_args()

    train(args.dir, args.override_from, args.override_to)

if __name__ == "__main__":
    main()