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
        print(f"[-] Папка '{data_dir}' не найдена!")
        sys.exit(1)

    supported_exts = (".xml", ".pdf")
    files = [os.path.join(data_dir, f) for f in os.listdir(data_dir) if f.lower().endswith(supported_exts)]
    
    if not files:
        print(f"[-] В папке '{data_dir}' нет поддерживаемых файлов (.xml, .pdf)!")
        return

    print(f"[*] Сканирование {len(files)} файлов в папке '{data_dir}'...")

    # 1. Считываем все файлы в память и определяем диапазон дат
    parsed_docs = []
    valid_dates = []

    for file_path in files:
        try:
            doc = parse_document(file_path)
            if doc and doc.items:
                parsed_docs.append(doc)
                # Проверяем валидность даты YYYY-MM-DD
                try:
                    d_obj = datetime.strptime(doc.doc_date, "%Y-%m-%d").date()
                    valid_dates.append(d_obj)
                except ValueError:
                    pass
        except Exception:
            continue

    if not parsed_docs:
        print("[-] Не удалось успешно распарсить ни один документ в папке.")
        return

    print(f"[+] Успешно прочитано документов: {len(parsed_docs)} из {len(files)}")

    # 2. Вычисляем динамический диапазон дат с буфером ±5 дней
    if valid_dates:
        min_doc_date = min(valid_dates)
        max_doc_date = max(valid_dates)
        
        # Сдвиг дат на 5 дней для компенсации задержек проведения
        auto_from = (min_doc_date - timedelta(days=5)).strftime("%Y-%m-%d")
        auto_to = (max_doc_date + timedelta(days=5)).strftime("%Y-%m-%d")
        
        print(f"    Даты в накладных: с {min_doc_date} по {max_doc_date}")
    else:
        auto_from = "2026-01-01"
        auto_to = "2026-12-31"

    # Приоритет флагам из командной строки, если они заданы вручную
    date_from = override_from or auto_from
    date_to = override_to or auto_to

    print(f"    Запрашиваемый период iiko: {date_from} — {date_to} (автоматически с буфером)")

    # 3. Загрузка живого пула номенклатуры (без архива и Яндекс.Еды)
    print("\n[*] Загрузка актуального каталога iiko и проверка папок...")
    active_products = client.get_active_stock_products()
    active_pool = {p["id"]: p for p in active_products}
    print(f"[+] Разрешенных активных товаров: {len(active_pool)}")

    # 4. Выгрузка накладных iiko за вычисленный период
    print(f"[*] Выгрузка истории накладных из iiko...")
    inv_resp = client.get(
        "/api/documents/export/incomingInvoice",
        params={"from": date_from, "to": date_to}
    )
    inv_root = ET.fromstring(inv_resp.content)
    iiko_docs = inv_root.findall(".//document")
    print(f"[+] Найдено накладных в iiko за этот период: {len(iiko_docs)}")

    # Индексируем накладные iiko для мгновенного поиска
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

    # 5. Сопоставление (строгий порядок + сверка цен + проверка папок)
    print("\n[*] Анализ сопоставлений...")
    perfect_matches = 0
    learned_items = 0

    for doc in parsed_docs:
        target_num = doc.doc_number
        target_sum = round(sum(it.sum for it in doc.items), 2)

        # Поиск документа в iiko: по номеру или уникальной сумме
        matched_iiko_doc = iiko_by_num.get(target_num)
        if matched_iiko_doc is None and target_sum in iiko_by_sum:
            candidates = iiko_by_sum[target_sum]
            if len(candidates) == 1:
                matched_iiko_doc = candidates[0]

        if matched_iiko_doc is None:
            continue

        supplier_id = matched_iiko_doc.findtext("supplier")
        iiko_items = matched_iiko_doc.findall(".//items/item")

        if len(doc.items) != len(iiko_items):
            continue

        is_order_perfect = True
        temp_pairs = []

        for d_item, i_item in zip(doc.items, iiko_items):
            i_amount = float(i_item.findtext("amount", 0))
            i_sum = float(i_item.findtext("sum", 0))

            qty_match = abs(d_item.quantity - i_amount) < 0.01
            sum_match = abs(d_item.sum - i_sum) < 1.0

            if not (qty_match and sum_match):
                is_order_perfect = False
                break

            p_id = i_item.findtext("product")
            
            # Проверка, что товар живой
            if p_id not in active_pool:
                is_order_perfect = False
                break

            prod_info = active_pool[p_id]
            temp_pairs.append({
                "supplier_id": supplier_id,
                "raw_name": d_item.raw_name,
                "product_id": p_id,
                "iiko_name": prod_info["name"],
                "article": d_item.article or prod_info["article"]
            })

        if is_order_perfect:
            perfect_matches += 1
            for pair in temp_pairs:
                record_mapping_vote(
                    supplier_id=pair["supplier_id"],
                    raw_name=pair["raw_name"],
                    product_id=pair["product_id"],
                    iiko_name=pair["iiko_name"],
                    article=pair["article"],
                    weight=1
                )
                learned_items += 1

            print(f"[✅ ИДЕАЛЬНО] {os.path.basename(doc.source_file):<30} | № {target_num:<10} | Сумма: {target_sum:>9.2f} руб. ({len(temp_pairs)} поз.)")

    print("\n" + "=" * 65)
    print(f"📊 [ИТОГ ОБУЧЕНИЯ]")
    print(f"  Обработано документов:          {len(parsed_docs)}")
    print(f"  Период дат документов:         {min_doc_date} — {max_doc_date}")
    print(f"  Выгружено из iiko (с буфером):  {date_from} — {date_to}")
    print(f"  Совпало накладных по порядку:  {perfect_matches}")
    print(f"  Достоверных связок в БД:       {learned_items}")
    print("=" * 65)

def main():
    parser = argparse.ArgumentParser(description="Автоматическое обучение базы сопоставлений iiko")
    parser.add_argument("--dir", default="diadoc_xmls", help="Папка с накладными (по умолчанию: diadoc_xmls)")
    parser.add_argument("--from-date", dest="override_from", default=None, help="Принудительная дата начала YYYY-MM-DD")
    parser.add_argument("--to-date", dest="override_to", default=None, help="Принудительная дата конца YYYY-MM-DD")
    args = parser.parse_args()

    train(args.dir, args.override_from, args.override_to)

if __name__ == "__main__":
    main()