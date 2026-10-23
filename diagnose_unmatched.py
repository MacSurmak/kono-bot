#!/usr/bin/env python3
import os
import sys
import json
import argparse
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

from parsers import parse_document
from iiko_client import client
from storage import init_db

init_db()


def diagnose(data_dir: str):
    if not os.path.exists(data_dir):
        print(f"[-] Directory '{data_dir}' does not exist")
        sys.exit(1)

    supported_exts = (".xml", ".pdf")
    files = [
        os.path.join(data_dir, f)
        for f in os.listdir(data_dir)
        if f.lower().endswith(supported_exts)
    ]
    print(f"[*] Scanning {len(files)} files in '{data_dir}'...")

    # 1. Parse incoming documents into memory
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

    if not valid_dates:
        print("[-] No valid documents found")
        return

    # 2. Determine date bounds with buffer
    min_date = min(valid_dates)
    max_date = max(valid_dates)
    date_from = (min_date - timedelta(days=5)).strftime("%Y-%m-%d")
    date_to = (max_date + timedelta(days=5)).strftime("%Y-%m-%d")
    print(f"[*] Querying iiko invoices from {date_from} to {date_to}...")

    # 3. Retrieve active stock catalog
    active_products = client.get_active_stock_products()
    active_pool = {p["id"]: p for p in active_products}

    # 4. Retrieve historical invoices from iiko
    inv_resp = client.get(
        "/api/documents/export/incomingInvoice",
        params={"from": date_from, "to": date_to},
    )
    inv_root = ET.fromstring(inv_resp.content)
    iiko_docs = inv_root.findall(".//document")

    # Index iiko invoices
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

    # 5. Diagnostic categorization
    stats = {
        "perfect_order": 0,
        "scrambled_solvable": 0,
        "scrambled_ambiguous": 0,
        "line_count_mismatch": 0,
        "not_found": 0,
        "archived_item_present": 0,
    }

    details = []

    for doc in parsed_docs:
        target_num = doc.doc_number
        target_sum = round(sum(it.sum for it in doc.items), 2)

        matched_iiko_doc = iiko_by_num.get(target_num)
        match_by = "NUMBER" if matched_iiko_doc is not None else None

        if matched_iiko_doc is None and target_sum in iiko_by_sum:
            candidates = iiko_by_sum[target_sum]
            if len(candidates) == 1:
                matched_iiko_doc = candidates[0]
                match_by = "UNIQUE_SUM"

        if matched_iiko_doc is None:
            stats["not_found"] += 1
            details.append(
                {
                    "file": os.path.basename(doc.source_file),
                    "doc_number": target_num,
                    "doc_date": doc.doc_date,
                    "supplier_name": doc.supplier_name,
                    "total_sum": target_sum,
                    "items_count": len(doc.items),
                    "status": "NOT_FOUND_IN_IIKO",
                    "diagnosis": "No matching incomingDocumentNumber or unique sum found in iiko export",
                }
            )
            continue

        iiko_num = matched_iiko_doc.findtext("documentNumber")
        iiko_items = matched_iiko_doc.findall(".//items/item")

        # Check line count
        if len(doc.items) != len(iiko_items):
            stats["line_count_mismatch"] += 1
            details.append(
                {
                    "file": os.path.basename(doc.source_file),
                    "doc_number": target_num,
                    "iiko_internal_num": iiko_num,
                    "matched_by": match_by,
                    "doc_lines": len(doc.items),
                    "iiko_lines": len(iiko_items),
                    "total_sum": target_sum,
                    "status": "LINE_COUNT_MISMATCH",
                    "diagnosis": f"Document has {len(doc.items)} lines, but iiko invoice has {len(iiko_items)} lines",
                }
            )
            continue

        # Check sequential order
        is_order_perfect = True
        has_archived = False
        unmatched_diadoc = []
        unmatched_iiko = []

        for idx, (d_item, i_item) in enumerate(zip(doc.items, iiko_items)):
            i_amount = float(i_item.findtext("amount", 0))
            i_sum = float(i_item.findtext("sum", 0))
            p_id = i_item.findtext("product")

            if p_id not in active_pool:
                has_archived = True

            qty_match = abs(d_item.quantity - i_amount) < 0.01
            sum_match = abs(d_item.sum - i_sum) < 1.0

            if not (qty_match and sum_match):
                is_order_perfect = False

        if is_order_perfect and not has_archived:
            stats["perfect_order"] += 1
            continue

        if has_archived:
            stats["archived_item_present"] += 1
            details.append(
                {
                    "file": os.path.basename(doc.source_file),
                    "doc_number": target_num,
                    "iiko_internal_num": iiko_num,
                    "status": "ARCHIVED_ITEM_PRESENT",
                    "diagnosis": "Contains at least one product that is currently in archive/inactive folder",
                }
            )
            continue

        # Check if rows are a solvable permutation (bipartite matching on qty and sum)
        iiko_rows = []
        for it in iiko_items:
            p_id = it.findtext("product")
            iiko_rows.append(
                {
                    "product_id": p_id,
                    "name": active_pool.get(p_id, {}).get("name", "UNKNOWN"),
                    "amount": float(it.findtext("amount", 0)),
                    "sum": float(it.findtext("sum", 0)),
                }
            )

        # Test greedy 1-to-1 matching by (quantity, sum)
        matched_pairs = []
        available_iiko = list(iiko_rows)
        for d_it in doc.items:
            candidate = None
            for i_it in available_iiko:
                if (
                    abs(d_it.quantity - i_it["amount"]) < 0.01
                    and abs(d_it.sum - i_it["sum"]) < 1.0
                ):
                    candidate = i_it
                    break
            if candidate:
                available_iiko.remove(candidate)
                matched_pairs.append(
                    {
                        "raw_name": d_it.raw_name,
                        "iiko_name": candidate["name"],
                        "qty": d_it.quantity,
                        "sum": d_it.sum,
                    }
                )

        if len(matched_pairs) == len(doc.items):
            stats["scrambled_solvable"] += 1
            details.append(
                {
                    "file": os.path.basename(doc.source_file),
                    "doc_number": target_num,
                    "iiko_internal_num": iiko_num,
                    "lines_count": len(doc.items),
                    "status": "SCRAMBLED_PERMUTATION_SOLVABLE",
                    "diagnosis": "All lines exist in iiko with matching quantities and sums, but row order is permuted",
                    "example_matches": matched_pairs[:3],
                }
            )
        else:
            stats["scrambled_ambiguous"] += 1
            details.append(
                {
                    "file": os.path.basename(doc.source_file),
                    "doc_number": target_num,
                    "iiko_internal_num": iiko_num,
                    "matched_count": len(matched_pairs),
                    "total_count": len(doc.items),
                    "status": "SCRAMBLED_AMBIGUOUS_PRICES",
                    "diagnosis": "Row order is permuted and price/qty combinations have discrepancies or multiple duplicates",
                }
            )

    # Save full telemetry
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "out")
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, "unmatched_diagnosis.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(details, f, ensure_ascii=False, indent=2)

    # Print summary
    print("\n" + "=" * 70)
    print("📊 DIAGNOSTIC SUMMARY:")
    print("=" * 70)
    print(f"  [1] Strict order matched:                       {stats['perfect_order']}")
    print(
        f"  [2] Permutation solvable:                       {stats['scrambled_solvable']}"
    )
    print(
        f"  [3] Ambiguous duplicate prices:                 {stats['scrambled_ambiguous']}"
    )
    print(
        f"  [4] Line count mismatch:                        {stats['line_count_mismatch']}"
    )
    print(
        f"  [5] Archived items present:                     {stats['archived_item_present']}"
    )
    print(f"  [6] Not found in iiko:                          {stats['not_found']}")
    print("=" * 70)
    print(f"[+] Diagnostic report written to: {report_path}\n")

    # Show solvable examples
    solvable_examples = [
        d for d in details if d["status"] == "SCRAMBLED_PERMUTATION_SOLVABLE"
    ]
    if solvable_examples:
        print(
            "💡 EXAMPLES OF SOLVABLE PERMUTATIONS (Scrambled rows with matching sums):"
        )
        for ex in solvable_examples[:3]:
            print(
                f"\n  • Invoice #{ex['doc_number']} (iiko #{ex['iiko_internal_num']}), lines: {ex['lines_count']}"
            )
            for pair in ex["example_matches"]:
                print(
                    f"    - {pair['raw_name'][:35]:<36} -> {pair['iiko_name'][:35]:<36} ({pair['qty']} qty, {pair['sum']:.2f} RUB)"
                )


def main():
    parser = argparse.ArgumentParser(
        description="Diagnostic utility for unmatched invoices"
    )
    parser.add_argument(
        "--dir", default="data/in/diadoc_xmls", help="Directory with invoice files"
    )
    args = parser.parse_args()
    diagnose(args.dir)


if __name__ == "__main__":
    main()
