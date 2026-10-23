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

    # Support both legal entities (СвЮЛУч) and individual entrepreneurs (СвИП)
    seller_jur = root.find(".//СвПрод/ИдСв/СвЮЛУч")
    seller_ip = root.find(".//СвПрод/ИдСв/СвИП")

    if seller_jur is not None:
        inn = seller_jur.attrib.get("ИННЮЛ", "").strip()
        seller_name = seller_jur.attrib.get("НаимОрг", "").strip()
    elif seller_ip is not None:
        inn = seller_ip.attrib.get("ИННФЛ", "").strip()
        fio_elem = seller_ip.find(".//ФИО")
        fio_parts = [
            fio_elem.attrib.get(k, "").strip()
            for k in ("Фамилия", "Имя", "Отчество")
            if fio_elem is not None and fio_elem.attrib.get(k)
        ]
        seller_name = f"ИП {' '.join(fio_parts)}".strip()
    else:
        inn = ""
        seller_name = ""

    consignee_elem = root.find(".//ГрузПолуч/Адрес/АдрИнф")
    consignee_addr = (
        consignee_elem.attrib.get("АдрТекст", "").strip() if consignee_elem is not None else ""
    )

    items = []
    for row in root.findall(".//ТаблСчФакт/СведТов"):
        code_elem = row.find(".//ДопСведТов")
        article = (
            code_elem.attrib.get("КодТов", "").strip() if code_elem is not None else ""
        )
        article = " ".join(article.replace("\xa0", " ").strip().split())

        raw_item_name = row.attrib.get("НаимТов", "").strip()
        clean_name = " ".join(raw_item_name.replace("\xa0", " ").strip().split())

        raw_vat = row.attrib.get("НалСт", "").strip().lower()
        if "без" in raw_vat:
            vat_val = 0.0
        else:
            digits = "".join(c for c in raw_vat if c.isdigit() or c == ".")
            vat_val = float(digits) if digits else 20.0

        items.append(
            RawInvoiceItem(
                line_num=int(row.attrib.get("НомСтр", 0)),
                raw_name=clean_name,
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
