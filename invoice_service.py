import xml.etree.ElementTree as ET
from rapidfuzz import process, fuzz
from models import RawInvoiceDocument
from iiko_client import client, ALLOWED_STORES
from storage import (
    record_mapping_vote,
    get_consensus_mapping,
    get_preferred_supplier,
    save_preferred_supplier
)

STORE_KEYWORDS = {
    "4841e49a-61b4-4f34-b51c-7cfb3ccad7ac": ["аэропорт", "ленинградский", "ленинградка", "д. 62", "дом 62"],
    "62b795dd-f0e2-4d3b-b354-5ff194b8dcd9": ["октябрьская", "серпуховская", "замоскворечье", "8/7", "большая серпуховская"]
}

def resolve_store(consignee_address: str) -> tuple[str, str]:
    addr = (consignee_address or "").lower()
    for s_id, keywords in STORE_KEYWORDS.items():
        if any(k in addr for k in keywords):
            return s_id, ALLOWED_STORES[s_id]

    print("\n" + "!" * 65)
    print(f"[?] Адрес в накладной: '{consignee_address or 'НЕ УКАЗАН'}'")
    print("    Выберите точку доставки:")
    print("    [1] Аэропорт (Ленинградский пр-т, 62)")
    print("    [2] Октябрьская (Большая Серпуховская, 8/7)")
    print("!" * 65)

    choices = {"1": "4841e49a-61b4-4f34-b51c-7cfb3ccad7ac", "2": "62b795dd-f0e2-4d3b-b354-5ff194b8dcd9"}
    while True:
        c = input("    Ваш выбор (1 или 2): ").strip()
        if c in choices:
            s_id = choices[c]
            return s_id, ALLOWED_STORES[s_id]

def resolve_supplier(inn: str, store_name: str) -> tuple[str, str]:
    pref = get_preferred_supplier(inn)
    if pref:
        return pref[0], pref[1]

    suppliers = client.get_suppliers_grouped()
    candidates = suppliers.get(inn, [])
    if not candidates:
        raise ValueError(f"Поставщик с ИНН {inn} не заведен в iiko!")

    if len(candidates) == 1:
        return candidates[0]["id"], candidates[0]["name"]

    print("\n" + "!" * 65)
    print(f"[?] По ИНН {inn} найдено несколько филиалов в iiko (целевая точка: {store_name}):")
    for idx, c in enumerate(candidates, 1):
        dep = f" (точки: {c['dept_codes']})" if c['dept_codes'] else " (все точки)"
        print(f"    [{idx}] {c['name']}{dep}")
    print("!" * 65)

    while True:
        c = input(f"    Выберите поставщика (1-{len(candidates)}): ").strip()
        if c.isdigit() and 1 <= int(c) <= len(candidates):
            chosen = candidates[int(c) - 1]
            save_preferred_supplier(inn, chosen["id"], chosen["name"])
            return chosen["id"], chosen["name"]

def resolve_item(supplier_id: str, raw_name: str, article: str, catalog: list) -> tuple[str, str]:
    consensus = get_consensus_mapping(supplier_id, raw_name)
    if consensus and not consensus["has_conflict"]:
        return consensus["product_id"], consensus["iiko_name"]

    if consensus and consensus["has_conflict"]:
        print(f"\n[⚠️ КОНФЛИКТ В ИСТОРИИ] Позиция: '{raw_name}'")
        for idx, var in enumerate(consensus["all_variants"], 1):
            pct = (var[3] / consensus["total_votes"]) * 100
            print(f"    [{idx}] {var[1]} (арт: {var[2]}) — выбрано {var[3]} раз ({pct:.0f}%)")
        print("    [0] Искать в каталоге вручную")
        c = input("    Ваш выбор: ").strip()
        if c.isdigit() and 1 <= int(c) <= len(consensus["all_variants"]):
            chosen = consensus["all_variants"][int(c) - 1]
            record_mapping_vote(supplier_id, raw_name, chosen[0], chosen[1], chosen[2], weight=3)
            return chosen[0], chosen[1]

    print(f"\n[?] НОВЫЙ ТОВАР: '{raw_name}'" + (f" (арт: {article})" if article else ""))
    choices = [p["name"] for p in catalog]
    matches = process.extract(raw_name, choices, limit=3, scorer=fuzz.token_sort_ratio)
    name_to_prod = {p["name"]: p for p in catalog}

    print("    Варианты из iiko:")
    for idx, (name, score, _) in enumerate(matches, 1):
        p = name_to_prod[name]
        print(f"    [{idx}] {name} (арт: {p['article']}) [Папка: {p['folder']}] ({score:.0f}%)")
    print("    [4] Ввести артикул iiko вручную")
    print("    [0] Пропустить позицию")

    while True:
        ans = input("    Ваш выбор (1-4, 0): ").strip()
        if ans in ("1", "2", "3"):
            chosen_name = matches[int(ans) - 1][0]
            prod = name_to_prod[chosen_name]
            record_mapping_vote(supplier_id, raw_name, prod["id"], prod["name"], article or prod["article"], weight=2)
            return prod["id"], prod["name"]
        elif ans == "4":
            manual = input("    Введите артикул iiko: ").strip()
            for p in catalog:
                if manual in (p["article"], p["id"]):
                    record_mapping_vote(supplier_id, raw_name, p["id"], p["name"], manual, weight=2)
                    return p["id"], p["name"]
            print("    Артикул не найден.")
        elif ans == "0":
            return None, None

def build_iiko_xml(doc: RawInvoiceDocument, store_id: str, supplier_id: str, matched_items: list) -> str:
    items_xml = "".join([f"""
        <item>
            <num>{it['num']}</num>
            <store>{store_id}</store>
            <product>{it['product_id']}</product>
            <amount>{it['amount']}</amount>
            <price>{it['price']}</price>
            <sum>{it['sum']}</sum>
            <vatPercent>{it['vat']}</vatPercent>
        </item>""" for it in matched_items])

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<document>
    <incomingDocumentNumber>{doc.doc_number}</incomingDocumentNumber>
    <incomingDate>{doc.doc_date}</incomingDate>
    <dateIncoming>{doc.doc_date}T12:00:00</dateIncoming>
    <status>NOT_PROCESSED</status>
    <supplier>{supplier_id}</supplier>
    <defaultStore>{store_id}</defaultStore>
    <comment>Автоматический импорт ({doc.source_file})</comment>
    <items>{items_xml}
    </items>
</document>"""