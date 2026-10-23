#!/usr/bin/env python3
import os
import sys
import argparse
import xml.etree.ElementTree as ET

from parsers import parse_document
from iiko_client import client
from invoice_service import (
    resolve_store,
    resolve_supplier,
    resolve_item,
    build_iiko_xml,
)


def main():
    parser = argparse.ArgumentParser(description="Import invoices to iiko (XML / PDF)")
    parser.add_argument("file_path", help="Path to invoice file (.xml or .pdf)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Simulation mode (no upload to iiko)"
    )
    args = parser.parse_args()

    # 1. Parse document via unified contract
    print(f"\n[*] Reading document: {os.path.basename(args.file_path)}...")
    doc = parse_document(args.file_path)
    print(f"[+] Parsed: Doc #{doc.doc_number} dated {doc.doc_date}")
    print(f"    Supplier: {doc.supplier_name} (INN: {doc.supplier_inn})")
    print(f"    Lines:    {len(doc.items)}")

    # 2. Resolve destination store and supplier
    store_id, store_name = resolve_store(doc.consignee_address)
    supplier_id, supplier_name = resolve_supplier(doc.supplier_inn, store_name)

    # 3. Load active stock catalog into RAM
    print(f"\n[*] Loading active iiko catalog into memory...")
    catalog = client.get_active_stock_products()
    print(f"[+] Active inventory pool: {len(catalog)}")

    # 4. Item matching with consensus resolution
    matched_items = []
    print("\n[*] Aligning line items...")
    for idx, item in enumerate(doc.items, 1):
        p_id, i_name = resolve_item(supplier_id, item.raw_name, item.article, catalog)
        if p_id:
            matched_items.append(
                {
                    "num": idx,
                    "product_id": p_id,
                    "iiko_name": i_name,
                    "raw_name": item.raw_name,
                    "amount": item.quantity,
                    "price": item.price,
                    "sum": item.sum,
                    "vat": item.vat_rate,
                }
            )
            print(f"  [{idx:02d}] {item.raw_name[:35]:<35} -> {i_name}")

    if not matched_items:
        print("[-] No items matched. Import aborted.")
        return

    # 5. Build iiko XML payload
    xml_payload = build_iiko_xml(doc, store_id, supplier_id, matched_items)

    # 6. Dry-run simulation bypass
    if args.dry_run:
        out_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "out"
        )
        os.makedirs(out_dir, exist_ok=True)
        preview_path = os.path.join(out_dir, "dry_run_preview.xml")
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(xml_payload)
        total_sum = sum(it["sum"] for it in matched_items)
        print("\n" + "=" * 75)
        print("🔍 [DRY-RUN] SIMULATION COMPLETE (NO DATA UPLOADED TO IIKO)")
        print(f"  Target Store:      {store_name}")
        print(f"  Supplier:          {supplier_name}")
        print(f"  Total Amount:      {total_sum:,.2f} RUB")
        print(f"  Preview XML:       {preview_path}")
        print("=" * 75)
        return

    # 7. Production upload (draft status)
    print(f"\n[*] Uploading draft invoice to store {store_name} in iiko...")
    res = client.upload_invoice(store_id, xml_payload)

    if res.status_code == 200 and "valid>true" in res.text:
        doc_no = ET.fromstring(res.content).findtext("documentNumber")
        print("\n" + "=" * 65)
        print(f"[🚀 SUCCESS] Draft invoice created in iiko!")
        print(f"  Store:            {store_name}")
        print(f"  Internal Number:  {doc_no}")
        print(f"  Incoming Number:  {doc.doc_number}")
        print("=" * 65)
    else:
        print(f"[-] Upload failed ({res.status_code}):\n{res.text}")


if __name__ == "__main__":
    main()
