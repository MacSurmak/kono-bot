import base64
from models import RawInvoiceDocument, RawInvoiceItem, InvoiceDocumentSchema
from gemini_rotator import rotator


def parse_pdf_gemini(file_path: str) -> RawInvoiceDocument:
    with open(file_path, "rb") as f:
        pdf_b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = (
        "You are an expert Russian accounting auditor. "
        "Extract all invoice metadata and line items from this document into the required structured schema."
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
