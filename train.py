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

    # 5. Multi-pass matching pipeline
    print("\n[*] Starting Multi-Pass alignment pipeline...")
    pass1_matched_docs = 0
    pass2_matched_docs = 0
    learned_items_count = 0

    unresolved_docs = []

    def extract_iiko_rows(doc_elem):
        rows = []
        for it in doc_elem.findall(".//items/item"):
            p_id = it.findtext("product")
            if p_id not in active_pool:
                return None
            prod = active_pool[p_id]
            rows.append({
                "product_id": p_id,
                "name": prod["name"],
                "article": prod["article"],
                "amount": float(it.findtext("amount", 0)),
                "sum": float(it.findtext("sum", 0))
            })
        return rows

    # --- PASS 1: Sequential matches and 100% bijective permutations ---
    print("\n--- [PASS 1] Exact Sequential and Bijective Permutations ---")
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
        iiko_rows = extract_iiko_rows(matched_iiko_doc)
        if not iiko_rows or len(doc.items) != len(iiko_rows):
            continue

        available_iiko = list(iiko_rows)
        matched_pairs = []

        for d_item in doc.items:
            candidate = None
            for idx, i_item in enumerate(available_iiko):
                if abs(d_item.quantity - i_item["amount"]) < 0.01 and abs(d_item.sum - i_item["sum"]) < 1.0:
                    candidate = available_iiko.pop(idx)
                    break

            if candidate:
                matched_pairs.append({
                    "supplier_id": supplier_id,
                    "raw_name": d_item.raw_name,
                    "product_id": candidate["product_id"],
                    "iiko_name": candidate["name"],
                    "article": d_item.article or candidate["article"]
                })

        if len(matched_pairs) == len(doc.items):
            pass1_matched_docs += 1
            for pair in matched_pairs:
                record_mapping_vote(
                    supplier_id=pair["supplier_id"],
                    raw_name=pair["raw_name"],
                    product_id=pair["product_id"],
                    iiko_name=pair["iiko_name"],
                    article=pair["article"],
                    weight=1
                )
                learned_items_count += 1
            print(f"[✅ PASS 1 BIJECTION] {os.path.basename(doc.source_file):<28} | Doc: {target_num:<10} | Sum: {target_sum:>9.2f} ({len(matched_pairs)} items)")
        else:
            unresolved_docs.append((doc, matched_iiko_doc, supplier_id, iiko_rows))

    # --- PASS 2: Anchor resolution with prior knowledge and elimination ---
    print(f"\n--- [PASS 2] Anchor Resolution & Deductive Elimination ({len(unresolved_docs)} candidates) ---")
    from storage import get_consensus_mapping

    for doc, matched_iiko_doc, supplier_id, iiko_rows in unresolved_docs:
        target_num = doc.doc_number
        target_sum = round(sum(it.sum for it in doc.items), 2)

        available_iiko = list(iiko_rows)
        remaining_doc_items = list(doc.items)
        resolved_pairs = []

        # Step 2.1: Anchor by previously learned consensus mappings
        for d_item in list(remaining_doc_items):
            consensus = get_consensus_mapping(supplier_id, d_item.raw_name)
            if consensus and not consensus["has_conflict"]:
                known_pid = consensus["product_id"]
                match_idx = None
                for idx, i_item in enumerate(available_iiko):
                    if i_item["product_id"] == known_pid:
                        qty_ok = abs(d_item.quantity - i_item["amount"]) < 0.01
                        sum_ok = abs(d_item.sum - i_item["sum"]) < 1.0
                        if qty_ok and sum_ok:
                            match_idx = idx
                            break
                if match_idx is not None:
                    matched_iiko_row = available_iiko.pop(match_idx)
                    remaining_doc_items.remove(d_item)
                    resolved_pairs.append({
                        "supplier_id": supplier_id,
                        "raw_name": d_item.raw_name,
                        "product_id": matched_iiko_row["product_id"],
                        "iiko_name": matched_iiko_row["name"],
                        "article": d_item.article or matched_iiko_row["article"]
                    })

        # Step 2.2: Greedy match for remaining lines with unique (quantity, sum)
        for d_item in list(remaining_doc_items):
            matching_candidates = [
                (idx, i_item) for idx, i_item in enumerate(available_iiko)
                if abs(d_item.quantity - i_item["amount"]) < 0.01 and abs(d_item.sum - i_item["sum"]) < 1.0
            ]
            if len(matching_candidates) == 1:
                idx, candidate = matching_candidates[0]
                available_iiko.pop(idx)
                remaining_doc_items.remove(d_item)
                resolved_pairs.append({
                    "supplier_id": supplier_id,
                    "raw_name": d_item.raw_name,
                    "product_id": candidate["product_id"],
                    "iiko_name": candidate["name"],
                    "article": d_item.article or candidate["article"]
                })

        # Step 2.3: Final elimination if exactly 1 pair remains with matching sum
        if len(remaining_doc_items) == 1 and len(available_iiko) == 1:
            last_d = remaining_doc_items[0]
            last_i = available_iiko[0]
            if abs(last_d.quantity - last_i["amount"]) < 0.01 and abs(last_d.sum - last_i["sum"]) < 1.0:
                remaining_doc_items.clear()
                available_iiko.clear()
                resolved_pairs.append({
                    "supplier_id": supplier_id,
                    "raw_name": last_d.raw_name,
                    "product_id": last_i["product_id"],
                    "iiko_name": last_i["name"],
                    "article": last_d.article or last_i["article"]
                })

        # If all items resolved in Pass 2
        if len(resolved_pairs) == len(doc.items):
            pass2_matched_docs += 1
            for pair in resolved_pairs:
                record_mapping_vote(
                    supplier_id=pair["supplier_id"],
                    raw_name=pair["raw_name"],
                    product_id=pair["product_id"],
                    iiko_name=pair["iiko_name"],
                    article=pair["article"],
                    weight=1
                )
                learned_items_count += 1
            print(f"[🎯 PASS 2 ANCHORED]  {os.path.basename(doc.source_file):<28} | Doc: {target_num:<10} | Sum: {target_sum:>9.2f} (Resolved {len(resolved_pairs)} items)")

    total_invoices_matched = pass1_matched_docs + pass2_matched_docs
    print("\n" + "=" * 70)
    print(f"📊 [MULTI-PASS TRAINING SUMMARY]")
    print(f"  Total documents processed:          {len(parsed_docs)}")
    print(f"  Matched in Pass 1 (Bijections):    {pass1_matched_docs}")
    print(f"  Matched in Pass 2 (Anchors):       {pass2_matched_docs}")
    print(f"  TOTAL INVOICES MATCHED:            {total_invoices_matched} of {len(parsed_docs)}")
    print(f"  VERIFIED MAPPINGS IN DB:           {learned_items_count}")
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