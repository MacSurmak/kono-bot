from dataclasses import dataclass, field
from typing import List
from pydantic import BaseModel, Field


# ================= PYDANTIC STRUCTURED OUTPUT SCHEMAS =================
class InvoiceItemSchema(BaseModel):
    line_num: int = Field(description="Line number in table")
    raw_name: str = Field(description="Exact product name from column 1a")
    article: str = Field(
        default="", description="Vendor article or item code if present"
    )
    quantity: float = Field(description="Quantity")
    price: float = Field(description="Unit price")
    sum: float = Field(description="Line total amount with VAT")
    vat_rate: float = Field(
        default=20.0, description="VAT percentage, e.g. 20.0 or 10.0"
    )


class InvoiceDocumentSchema(BaseModel):
    doc_number: str = Field(description="Invoice or document number")
    doc_date: str = Field(description="Document date in YYYY-MM-DD format")
    supplier_inn: str = Field(description="Supplier taxpayer ID (INN), digits only")
    supplier_name: str = Field(description="Supplier company name")
    consignee_address: str = Field(
        default="", description="Delivery address or consignee"
    )
    items: List[InvoiceItemSchema] = Field(description="List of line items")


# ================= INTERNAL DTO CONTRACTS =================
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
