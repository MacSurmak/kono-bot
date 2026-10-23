import xml.etree.ElementTree as ET
from rapidfuzz import process, fuzz
from models import RawInvoiceDocument
from config import ALLOWED_STORES, STORE_KEYWORDS
from iiko_client import client
from storage import (
    record_mapping_vote,
    get_consensus_mapping,
    get_preferred_supplier,
    save_preferred_supplier,
)


def resolve_store(consignee_address: str) -> tuple[str, str]:
    addr = (consignee_address or "").lower()
    for s_id, keywords in STORE_KEYWORDS.items():
        if any(k in addr for k in keywords):
            return s_id, ALLOWED_STORES[s_id]

    print("\n" + "!" * 65)
    print(f"[?] Invoice consignee address: '{consignee_address or 'NOT SPECIFIED'}'")
    print("    Select target delivery store:")
    store_ids = list(ALLOWED_STORES.keys())
    for idx, s_id in enumerate(store_ids, 1):
        print(f"    [{idx}] {ALLOWED_STORES[s_id]}")
    print("!" * 65)

    choice_map = {str(idx): s_id for idx, s_id in enumerate(store_ids, 1)}

    while True:
        c = input(f"    Your choice (1-{len(store_ids)}): ").strip()
        if c in choice_map:
            s_id = choice_map[c]
            return s_id, ALLOWED_STORES[s_id]


def resolve_supplier(inn: str, store_name: str) -> tuple[str, str]:
    pref = get_preferred_supplier(inn)
    if pref:
        return pref[0], pref[1]

    suppliers = client.get_suppliers_grouped()
    candidates = suppliers.get(inn, [])
    if not candidates:
        raise ValueError(f"Supplier with INN {inn} not registered in iiko!")

    if len(candidates) == 1:
        return candidates[0]["id"], candidates[0]["name"]

    print("\n" + "!" * 65)
    print(
        f"[?] Multiple supplier entries found for INN {inn} (target store: {store_name}):"
    )
    for idx, c in enumerate(candidates, 1):
        dep = (
            f" (departments: {c['dept_codes']})"
            if c["dept_codes"]
            else " (all departments)"
        )
        print(f"    [{idx}] {c['name']}{dep}")
    print("!" * 65)

    while True:
        c = input(f"    Select supplier (1-{len(candidates)}): ").strip()
        if c.isdigit() and 1 <= int(c) <= len(candidates):
            chosen = candidates[int(c) - 1]
            save_preferred_supplier(inn, chosen["id"], chosen["name"])
            return chosen["id"], chosen["name"]


def resolve_item(
    supplier_id: str, raw_name: str, article: str, catalog: list
) -> tuple[str, str]:
    consensus = get_consensus_mapping(supplier_id, raw_name)
    if consensus and not consensus["has_conflict"]:
        return consensus["product_id"], consensus["iiko_name"]

    if consensus and consensus["has_conflict"]:
        print(f"\n[⚠️ HISTORICAL CONFLICT] Item: '{raw_name}'")
        for idx, var in enumerate(consensus["all_variants"], 1):
            pct = (var[3] / consensus["total_votes"]) * 100
            print(
                f"    [{idx}] {var[1]} (sku: {var[2]}) — selected {var[3]} times ({pct:.0f}%)"
            )
        print("    [0] Search catalog manually")
        c = input("    Select correct variant: ").strip()
        if c.isdigit() and 1 <= int(c) <= len(consensus["all_variants"]):
            chosen = consensus["all_variants"][int(c) - 1]
            record_mapping_vote(
                supplier_id, raw_name, chosen[0], chosen[1], chosen[2], weight=3
            )
            return chosen[0], chosen[1]

    print(f"\n[?] NEW ITEM: '{raw_name}'" + (f" (sku: {article})" if article else ""))
    choices = [p["name"] for p in catalog]
    matches = process.extract(raw_name, choices, limit=3, scorer=fuzz.token_sort_ratio)
    name_to_prod = {p["name"]: p for p in catalog}

    print("    iiko catalog candidates:")
    for idx, (name, score, _) in enumerate(matches, 1):
        p = name_to_prod[name]
        print(
            f"    [{idx}] {name} (sku: {p['article']}) [Folder: {p['folder']}] ({score:.0f}%)"
        )
    print("    [4] Enter iiko SKU manually")
    print("    [0] Skip item")

    while True:
        ans = input("    Your choice (1-4, 0): ").strip()
        if ans in ("1", "2", "3"):
            chosen_name = matches[int(ans) - 1][0]
            prod = name_to_prod[chosen_name]
            record_mapping_vote(
                supplier_id,
                raw_name,
                prod["id"],
                prod["name"],
                article or prod["article"],
                weight=2,
            )
            return prod["id"], prod["name"]
        elif ans == "4":
            manual = input("    Enter iiko SKU: ").strip()
            for p in catalog:
                if manual in (p["article"], p["id"]):
                    record_mapping_vote(
                        supplier_id, raw_name, p["id"], p["name"], manual, weight=2
                    )
                    return p["id"], p["name"]
            print("    SKU not found.")
        elif ans == "0":
            return None, None


import xml.sax.saxutils as xml_escape


def build_iiko_xml(
    doc: RawInvoiceDocument, store_id: str, supplier_id: str, matched_items: list
) -> str:
    escaped_doc_num = xml_escape.escape(doc.doc_number)
    escaped_comment = xml_escape.escape(f"Автоматический импорт ({doc.source_file})")

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
    <incomingDocumentNumber>{escaped_doc_num}</incomingDocumentNumber>
    <incomingDate>{doc.doc_date}</incomingDate>
    <dateIncoming>{doc.doc_date}T12:00:00</dateIncoming>
    <status>NOT_PROCESSED</status>
    <supplier>{supplier_id}</supplier>
    <defaultStore>{store_id}</defaultStore>
    <comment>{escaped_comment}</comment>
    <items>{items_xml}
    </items>
</document>"""
