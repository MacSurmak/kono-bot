import json
import base64
from models import RawInvoiceDocument, RawInvoiceItem
from gemini_rotator import rotator

def parse_pdf_gemini(file_path: str) -> RawInvoiceDocument:
    with open(file_path, "rb") as f:
        pdf_b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = """Ты эксперт-бухгалтер РФ. Извлеки данные из УПД/счета-фактуры строго в JSON:
{
  "doc_number": "номер документа",
  "doc_date": "дата в формате YYYY-MM-DD",
  "supplier_inn": "ИНН продавца (только цифры)",
  "supplier_name": "название продавца",
  "consignee_address": "адрес доставки/грузополучателя",
  "items": [
    {
      "line_num": 1,
      "raw_name": "точное наименование товара из гр 1а",
      "article": "",
      "quantity": 0.0,
      "price": 0.0,
      "sum": 0.0,
      "vat_rate": 20.0
    }
  ]
}
Ответь ТОЛЬКО валидным JSON без markdown."""

    input_payload = [
        {"type": "document", "data": pdf_b64, "mime_type": "application/pdf"},
        {"type": "text", "text": prompt}
    ]

    # Вызываем через ротатор
    raw_text = rotator.execute_interaction(input_payload)
    text = raw_text.replace("```json", "").replace("```", "").strip()
    data = json.loads(text)

    items = []
    for it in data.get("items", []):
        raw_vat = str(it.get("vat_rate", 20.0))
        digits = "".join(c for c in raw_vat if c.isdigit() or c == ".")
        vat_val = float(digits) if digits else 20.0

        items.append(RawInvoiceItem(
            line_num=int(it.get("line_num", 0)),
            raw_name=str(it.get("raw_name", "")).strip(),
            article=str(it.get("article", "")).strip(),
            quantity=float(it.get("quantity", 0)),
            price=float(it.get("price", 0)),
            sum=float(it.get("sum", 0)),
            vat_rate=vat_val
        ))

    return RawInvoiceDocument(
        doc_number=str(data.get("doc_number", "")).strip(),
        doc_date=str(data.get("doc_date", "")).strip(),
        supplier_inn=str(data.get("supplier_inn", "")).strip(),
        supplier_name=str(data.get("supplier_name", "")).strip(),
        consignee_address=str(data.get("consignee_address", "")).strip(),
        items=items,
        source_file=file_path
    )