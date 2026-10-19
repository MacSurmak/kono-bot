from dataclasses import dataclass, field
from typing import List

@dataclass
class RawInvoiceItem:
    line_num: int
    raw_name: str
    article: str
    quantity: float
    price: float
    sum: float
    vat_rate: float

@dataclass
class RawInvoiceDocument:
    doc_number: str
    doc_date: str  # Format: YYYY-MM-DD
    supplier_inn: str
    supplier_name: str
    consignee_address: str
    items: List[RawInvoiceItem] = field(default_factory=list)
    source_file: str = ""