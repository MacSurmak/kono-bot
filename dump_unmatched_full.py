#!/usr/bin/env python3
import os
import sys
import argparse
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

from parsers import parse_document
from iiko_client import client

def dump_comparison(data_dir: str, target_doc: str = None, output_file: str = "unmatched_full_dump.txt"):
    if not os.path.exists(data_dir):
        print(f"[-] Directory '{data_dir}' not found!")
        sys.exit(1)

    supported_exts = (".xml", ".pdf")
    files = [os.path.join(data_dir, f) for f in os.listdir(data_dir) if f.lower().endswith(supported_exts)]
    
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
        print("[-] No valid documents found.")
        return

    # Calculate date bounds with +/- 5-day buffer
    min_date = min(valid_dates)
    max_date = max(valid_dates)
    date_from = (min_date - timedelta(days=5)).strftime("%Y-%m-%d")
    date_to = (max_date + timedelta(days=5)).strftime("%Y-%m-%d")

    # Fetch active products for name resolution
    active_products = client.get_active_stock_products()
    active_pool = {p["id"]: p for p in active_products}

    # Fetch iiko historical invoices
    inv_resp = client.get(
        "/api/documents/export/incomingInvoice",
        params={"from": date_from, "to": date_to}
    )
    inv_root = ET.fromstring(inv_resp.content)
    iiko_docs = inv_root.findall(".//document")

    # Index iiko invoices by number and sum
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

    output_lines = []

    def log(msg=""):
        output_lines.append(msg)
        if target_doc:
            print(msg)

    processed_count = 0

    for doc in parsed_docs:
        # Filter by specific document if requested
        if target_doc and target_doc.lower() not in doc.doc_number.lower():
            continue

        target_num = doc.doc_number
        target_sum = round(sum(it.sum for it in doc.items), 2)

        matched_iiko_doc = iiko_by_num.get(target_num)
        if matched_iiko_doc is None and target_sum in iiko_by_sum:
            candidates = iiko_by_sum[target_sum]
            if len(candidates) == 1:
                matched_iiko_doc = candidates[0]

        if matched_iiko_doc is None:
            continue

        iiko_num = matched_iiko_doc.findtext("documentNumber")
        raw_iiko_items = matched_iiko_doc.findall(".//items/item")

        iiko_rows = []
        for idx, it in enumerate(raw_iiko_items, 1):
            p_id = it.findtext("product")
            prod = active_pool.get(p_id, {"name": "UNKNOWN / ARCHIVED", "article": ""})
            iiko_rows.append({
                "idx": idx,
                "product_id": p_id,
                "name": prod["name"],
                "article": prod["article"],
                "amount": float(it.findtext("amount", 0)),
                "price": float(it.findtext("price", 0)),
                "sum": float(it.findtext("sum", 0))
            })

        # Find line-by-line pairings
        available_iiko = list(iiko_rows)
        diadoc_matches = {}

        for d_idx, d_item in enumerate(doc.items):
            match = None
            for i_item in available_iiko:
                qty_ok = abs(d_item.quantity - i_item["amount"]) < 0.01
                sum_ok = abs(d_item.sum - i_item["sum"]) < 1.0
                if qty_ok and sum_ok:
                    match = i_item
                    break
            if match:
                available_iiko.remove(match)
                diadoc_matches[d_idx] = match

        # Skip perfect 100% matches unless explicitly requested via --doc
        if len(diadoc_matches) == len(doc.items) and not target_doc:
            continue

        processed_count += 1
        log("\n" + "=" * 110)
        log(f"DOCUMENT: {doc.doc_number} (iiko #{iiko_num}) | Date: {doc.doc_date} | Supplier: {doc.supplier_name}")
        log(f"File: {os.path.basename(doc.source_file)}")
        log(f"Totals: Diadoc = {target_sum:.2f} ({len(doc.items)} lines) | iiko = {sum(r['sum'] for r in iiko_rows):.2f} ({len(iiko_rows)} lines)")
        log("-" * 110)

        # TABLE 1: DIADOC
        log(f"{'#':<3} | {'ARTICLE':<14} | {'DIADOC NAME':<42} | {'QTY':>8} | {'PRICE':>9} | {'SUM':>10} | {'STATUS'}")
        log("-" * 110)
        for d_idx, d_item in enumerate(doc.items, 1):
            matched_i = diadoc_matches.get(d_idx - 1)
            status_str = f"-> iiko line #{matched_i['idx']}" if matched_i else "❌ UNMATCHED"
            log(f"{d_idx:<3} | {d_item.article[:12]:<14} | {d_item.raw_name[:40]:<42} | {d_item.quantity:>8.2f} | {d_item.price:>9.2f} | {d_item.sum:>10.2f} | {status_str}")

        # TABLE 2: IIKO
        matched_iiko_indices = {m["idx"] for m in diadoc_matches.values()}
        log("\n" + f"{'#':<3} | {'ARTICLE':<14} | {'IIKO PRODUCT NAME':<42} | {'AMOUNT':>8} | {'PRICE':>9} | {'SUM':>10} | {'STATUS'}")
        log("-" * 110)
        for i_item in iiko_rows:
            matched_d_idx = [d_idx + 1 for d_idx, m in diadoc_matches.items() if m["idx"] == i_item["idx"]]
            status_str = f"<- Diadoc line #{matched_d_idx[0]}" if matched_d_idx else "❌ UNMATCHED"
            log(f"{i_item['idx']:<3} | {i_item['article'][:12]:<14} | {i_item['name'][:40]:<42} | {i_item['amount']:>8.2f} | {i_item['price']:>9.2f} | {i_item['sum']:>10.2f} | {status_str}")

        log("=" * 110)

    # Save full dump to file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))

    if not target_doc:
        print(f"[+] Full side-by-side dump for {processed_count} unmatched invoices written to: {output_file}")

def main():
    parser = argparse.ArgumentParser(description="Dump full side-by-side tables for unmatched invoices")
    parser.add_argument("--dir", default="diadoc_xmls", help="Directory with invoice files")
    parser.add_argument("--doc", default=None, help="Specific document number to inspect directly in terminal")
    parser.add_argument("--out", default="unmatched_full_dump.txt", help="Output file for complete dump")
    args = parser.parse_args()

    dump_comparison(args.dir, args.doc, args.out)

if __name__ == "__main__":
    main()
