import xml.sax.saxutils as xml_escape
from models import RawInvoiceDocument


def build_iiko_xml(
    doc: RawInvoiceDocument, store_id: str, supplier_id: str, matched_items: list
) -> str:
    escaped_doc_num = xml_escape.escape(doc.doc_number)

    item_blocks = []
    for it in matched_items:
        coeff = float(it["coefficient"])
        if coeff <= 0:
            raise ValueError(f"Invalid packaging coefficient {coeff} for item #{it['num']}")

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

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<document>
    <incomingDocumentNumber>{escaped_doc_num}</incomingDocumentNumber>
    <incomingDate>{doc.doc_date}</incomingDate>
    <dateIncoming>{doc.doc_date}T12:00:00</dateIncoming>
    <status>NOT_PROCESSED</status>
    <supplier>{supplier_id}</supplier>
    <defaultStore>{store_id}</defaultStore>
    <comment></comment>
    <items>{items_xml}
    </items>
</document>"""
