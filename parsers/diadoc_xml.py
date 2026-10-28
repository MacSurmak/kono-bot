import xml.etree.ElementTree as ET
from models import RawInvoiceDocument, RawInvoiceItem


def parse_diadoc_xml(file_path: str) -> RawInvoiceDocument:
    tree = ET.parse(file_path)
    root = tree.getroot()

    doc_elem = root.find(".//СвСчФакт")
    if doc_elem is None:
        doc_elem = root.find(".//Документ")
    if doc_elem is None:
        raise ValueError("Invalid Diadoc XML: neither 'СвСчФакт' nor 'Документ' root element found")

    doc_num = doc_elem.attrib.get("НомерДок", "").strip()
    if not doc_num:
        raise ValueError("Invalid Diadoc XML: missing required attribute 'НомерДок'")

    raw_date = doc_elem.attrib.get("ДатаДок", "").strip()
    if not raw_date:
        raise ValueError("Invalid Diadoc XML: missing required attribute 'ДатаДок'")

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
        raise ValueError("Invalid Diadoc XML: missing seller details ('СвЮЛУч' or 'СвИП')")

    if not inn:
        raise ValueError("Invalid Diadoc XML: seller INN is missing or empty")
    if not seller_name:
        raise ValueError("Invalid Diadoc XML: seller name is missing or empty")

    consignee_elem = root.find(".//ГрузПолуч/Адрес/АдрИнф")
    consignee_addr = (
        consignee_elem.attrib.get("АдрТекст", "").strip()
        if consignee_elem is not None
        else ""
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
        if not raw_vat:
            raise ValueError(f"Line #{row.attrib.get('НомСтр', '?')} missing required VAT attribute 'НалСт'")

        if "без" in raw_vat:
            vat_val = 0.0
        else:
            digits = "".join(c for c in raw_vat if c.isdigit() or c == ".")
            if not digits:
                raise ValueError(
                    f"Line #{row.attrib.get('НомСтр', '?')} has unparseable VAT rate: '{raw_vat}'"
                )
            vat_val = float(digits)

        line_num_str = row.attrib.get("НомСтр")
        if not line_num_str:
            raise ValueError("Item row missing required line number 'НомСтр'")

        qty_str = row.attrib.get("КолТов")
        if qty_str is None or not qty_str.strip():
            raise ValueError(f"Line #{line_num_str} missing required quantity 'КолТов'")

        price_str = row.attrib.get("ЦенаТов")
        if price_str is None or not price_str.strip():
            raise ValueError(f"Line #{line_num_str} missing required price 'ЦенаТов'")

        sum_str = row.attrib.get("СтТовУчНал")
        if sum_str is None or not sum_str.strip():
            raise ValueError(f"Line #{line_num_str} missing required sum with VAT 'СтТовУчНал'")

        items.append(
            RawInvoiceItem(
                line_num=int(line_num_str),
                raw_name=clean_name,
                article=article,
                quantity=float(qty_str),
                price=float(price_str),
                sum=float(sum_str),
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
