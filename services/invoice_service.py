# ==============================================================================
# ARCHITECTURAL INVARIANT: COMPUTATIONAL FAIL-FAST & MATHEMATICAL INVARIANTS
#
# RULE: Calculations for physical inventory amounts and unit prices must be strictly
# verified. Quantities must be strictly positive before computing unit prices.
#
# FORBIDDEN:
# - Dividing by zero or falling back to raw unit price `else it["price"]`.
# - Injecting empty stub tags (e.g. `<comment></comment>`) into payloads.
# ==============================================================================

import xml.sax.saxutils as xml_escape
from models import RawInvoiceDocument

DEFAULT_INVOICE_INCOMING_TIME = "12:00:00"


def build_iiko_xml(
    doc: RawInvoiceDocument, store_id: str, supplier_id: str, matched_items: list
) -> str:
    escaped_doc_num = xml_escape.escape(doc.doc_number)
    sorted_items = sorted(matched_items, key=lambda x: int(x["num"]))

    item_blocks = []
    for it in sorted_items:
        coeff = float(it["coefficient"])
        if coeff <= 0:
            raise ValueError(
                f"Invalid packaging coefficient {coeff} for item #{it['num']}"
            )

        final_amount = round(it["amount"] * coeff, 4)
        if final_amount <= 0:
            raise ValueError(
                f"Calculated amount for item #{it['num']} must be positive, got {final_amount}"
            )
        final_price = round(it["sum"] / final_amount, 4)

        item_blocks.append(f"""
        <item>
            <num>{it['num']}</num>
            <store>{store_id}</store>
            <product>{it['product_id']}</product>
            <amount>{final_amount}</amount>
            <price>{final_price}</price>
            <sum>{it['sum']}</sum>
            <vatPercent>{it['vat']}</vatPercent>
        </item>""")

    items_xml = "".join(item_blocks)

    incoming_datetime = f"{doc.doc_date}T{DEFAULT_INVOICE_INCOMING_TIME}"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<document>
    <incomingDocumentNumber>{escaped_doc_num}</incomingDocumentNumber>
    <incomingDate>{doc.doc_date}</incomingDate>
    <dateIncoming>{incoming_datetime}</dateIncoming>
    <status>NOT_PROCESSED</status>
    <supplier>{supplier_id}</supplier>
    <defaultStore>{store_id}</defaultStore>
    <items>{items_xml}
    </items>
</document>"""
