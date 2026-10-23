import os
from models import RawInvoiceDocument
from .diadoc_xml import parse_diadoc_xml
from .gemini_pdf import parse_pdf_gemini

def parse_document(file_path: str) -> RawInvoiceDocument:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".xml":
        return parse_diadoc_xml(file_path)
    elif ext == ".pdf":
        return parse_pdf_gemini(file_path)
    else:
        raise ValueError(f"Unsupported file format: '{ext}'. Supported formats: .xml, .pdf")
