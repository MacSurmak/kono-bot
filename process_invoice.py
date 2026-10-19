#!/usr/bin/env python3
import os
import sys
import argparse
import xml.etree.ElementTree as ET

from parsers import parse_document
from iiko_client import client
from invoice_service import resolve_store, resolve_supplier, resolve_item, build_iiko_xml

def main():
    parser = argparse.ArgumentParser(description="Импорт накладных в iiko (XML / PDF)")
    parser.add_argument("file_path", help="Путь к файлу накладной (.xml или .pdf)")
    parser.add_argument("--dry-run", action="store_true", help="Режим симуляции (без загрузки в iiko)")
    args = parser.parse_args()

    # 1. Parse document via unified contract
    print(f"\n[*] Чтение документа: {os.path.basename(args.file_path)}...")
    doc = parse_document(args.file_path)
    print(f"[+] Распарсен: № {doc.doc_number} от {doc.doc_date}")
    print(f"    Поставщик: {doc.supplier_name} (ИНН {doc.supplier_inn})")
    print(f"    Позиций:   {len(doc.items)}")

    # 2. Resolve destination store and supplier
    store_id, store_name = resolve_store(doc.consignee_address)
    supplier_id, supplier_name = resolve_supplier(doc.supplier_inn, store_name)

    # 3. Load active stock catalog into RAM
    print(f"\n[*] Загрузка каталога iiko в память...")
    catalog = client.get_active_stock_products()

    # 4. Item matching with consensus resolution
    matched_items = []
    print("\n[*] Сопоставление товаров...")
    for idx, item in enumerate(doc.items, 1):
        p_id, i_name = resolve_item(supplier_id, item.raw_name, item.article, catalog)
        if p_id:
            matched_items.append({
                "num": idx,
                "product_id": p_id,
                "iiko_name": i_name,
                "raw_name": item.raw_name,
                "amount": item.quantity,
                "price": item.price,
                "sum": item.sum,
                "vat": item.vat_rate
            })
            print(f"  [{idx:02d}] {item.raw_name[:35]:<35} -> {i_name}")

    if not matched_items:
        print("[-] Ни одна позиция не сопоставлена. Импорт отменен.")
        return

    # 5. Build iiko XML payload
    xml_payload = build_iiko_xml(doc, store_id, supplier_id, matched_items)

    # 6. Dry-run simulation bypass
    if args.dry_run:
        with open("dry_run_preview.xml", "w", encoding="utf-8") as f:
            f.write(xml_payload)
        total_sum = sum(it["sum"] for it in matched_items)
        print("\n" + "="*75)
        print("🔍 [DRY-RUN] СИМУЛЯЦИЯ ЗАВЕРШЕНА (В IIKO НИЧЕГО НЕ ОТПРАВЛЯЛОСЬ)")
        print(f"  Склад:             {store_name}")
        print(f"  Поставщик:         {supplier_name}")
        print(f"  Сумма документа:   {total_sum:,.2f} руб.")
        print(f"  Файл предпросмотра: dry_run_preview.xml")
        print("="*75)
        return

    # 7. Production upload (draft status)
    print(f"\n[*] Отправка черновика на склад {store_name} в iiko...")
    res = client.upload_invoice(store_id, xml_payload)

    if res.status_code == 200 and "valid>true" in res.text:
        doc_no = ET.fromstring(res.content).findtext("documentNumber")
        print("\n" + "="*65)
        print(f"[🚀 УСПЕХ] Черновик накладной создан в iiko!")
        print(f"  Склад:                {store_name}")
        print(f"  Внутренний номер:     {doc_no}")
        print(f"  Входящий номер УПД:   {doc.doc_number}")
        print("="*65)
    else:
        print(f"[-] Ошибка загрузки ({res.status_code}):\n{res.text}")

if __name__ == "__main__":
    main()