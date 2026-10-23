import xml.etree.ElementTree as ET
from models import RawInvoiceDocument, RawInvoiceItem


def parse_diadoc_xml(file_path: str) -> RawInvoiceDocument:
    tree = ET.parse(file_path)
    root = tree.getroot()

    doc_elem = root.find(".//СвСчФакт")
    if doc_elem is None:
        doc_elem = root.find(".//Документ")

    doc_num = doc_elem.attrib.get("НомерДок", "").strip()
    raw_date = doc_elem.attrib.get("ДатаДок", "").strip()

    if "." in raw_date:
        d, m, y = raw_date.split(".")
        doc_date = f"{y}-{m}-{d}"
    else:
        doc_date = raw_date

    seller = root.find(".//СвПрод/ИдСв/СвЮЛУч")
    inn = seller.attrib.get("ИННЮЛ", "").strip() if seller is not None else ""
    seller_name = seller.attrib.get("НаимОрг", "").strip() if seller is not None else ""

    consignee_elem = root.find(".//ГрузПолуч/Адрес/АдрИнф")
    consignee_addr = (
        consignee_elem.attrib.get("АдрТекст", "") if consignee_elem is not None else ""
    )

    items = []
    for row in root.findall(".//ТаблСчФакт/СведТов"):
        code_elem = row.find(".//ДопСведТов")
        article = (
            code_elem.attrib.get("КодТов", "").strip() if code_elem is not None else ""
        )

        raw_vat = row.attrib.get("НалСт", "20%")
        digits = "".join(c for c in raw_vat if c.isdigit() or c == ".")
        vat_val = float(digits) if digits else 20.0

        items.append(
            RawInvoiceItem(
                line_num=int(row.attrib.get("НомСтр", 0)),
                raw_name=row.attrib.get("НаимТов", "").strip(),
                article=article,
                quantity=float(row.attrib.get("КолТов", 0)),
                price=float(row.attrib.get("ЦенаТов", 0)),
                sum=float(row.attrib.get("СтТовУчНал", 0)),
                vat_rate=vat_val,
            )
        )

    return RawInvoiceDocument(
        doc_number=doc_num,
        doc_date=doc_date,
        supplier_inn=inn,
        supplier_name=seller_name,
        consignee_address=consignee_addr,
        items=items,
        source_file=file_path,
    )
