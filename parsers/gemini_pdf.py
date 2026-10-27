import io
import base64
from pypdf import PdfReader, PdfWriter
from models import RawInvoiceDocument, RawInvoiceItem, InvoiceDocumentSchema
from services.gemini_rotator import rotator


def normalize_pdf_rotation(file_path: str) -> bytes:
    """Detects and normalizes rotated PDF pages to upright 0-degree orientation."""
    try:
        reader = PdfReader(file_path)
        writer = PdfWriter()
        has_rotated_pages = False

        for page in reader.pages:
            rot = page.rotation
            if rot != 0:
                page.transfer_rotation_to_content()
                page.rotation = 0
                has_rotated_pages = True
            writer.add_page(page)

        if has_rotated_pages:
            buf = io.BytesIO()
            writer.write(buf)
            return buf.getvalue()
    except Exception as e:
        from loguru import logger

        logger.warning(
            f"Failed to normalize PDF rotation for '{file_path}': {e}. Using raw file bytes."
        )

    with open(file_path, "rb") as f:
        return f.read()


def parse_pdf_gemini(file_path: str) -> RawInvoiceDocument:
    pdf_bytes = normalize_pdf_rotation(file_path)
    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    prompt = (
        "You are an expert Russian accounting auditor and OCR specialist.\n"
        "CRITICAL ORIENTATION AND DIGIT ACCURACY INSTRUCTIONS:\n"
        "1. Some pages, scans, or tables may be rotated sideways (90°, 180°, or 270°).\n"
        "   Inspect the document horizontally and upright before reading text.\n"
        "2. Russian INN (taxpayer ID) for legal entities (ООО/АО) contains EXACTLY 10 digits.\n"
        "   Russian INN for individual entrepreneurs (ИП) contains EXACTLY 12 digits.\n"
        "   Scrutinize every digit of the seller's INN (do not confuse 1 with 7, 3 with 8, or 6 with 7).\n"
        "3. Cross-check INN against the supplier's name and address.\n"
        "4. Extract all invoice metadata and line items from this document into the required structured schema."
    )

    input_payload = [
        {"type": "document", "data": pdf_b64, "mime_type": "application/pdf"},
        {"type": "text", "text": prompt},
    ]

    # Execute with Pydantic Structured Output constraint
    raw_response = rotator.execute_interaction(
        input_payload, schema=InvoiceDocumentSchema
    )
    validated_doc = InvoiceDocumentSchema.model_validate_json(raw_response)

    items = [
        RawInvoiceItem(
            line_num=it.line_num,
            raw_name=it.raw_name.strip(),
            article=it.article.strip(),
            quantity=it.quantity,
            price=it.price,
            sum=it.sum,
            vat_rate=it.vat_rate,
        )
        for it in validated_doc.items
    ]

    return RawInvoiceDocument(
        doc_number=validated_doc.doc_number.strip(),
        doc_date=validated_doc.doc_date.strip(),
        supplier_inn=validated_doc.supplier_inn.strip(),
        supplier_name=validated_doc.supplier_name.strip(),
        consignee_address=validated_doc.consignee_address.strip(),
        items=items,
        source_file=file_path,
    )
