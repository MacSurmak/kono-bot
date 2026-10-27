from typing import List, Dict, Any
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from lexicon import t
from config import ALLOWED_STORES


def get_pdf_confirmation_kb(doc_id: str) -> InlineKeyboardMarkup:
    """Generates confirmation keyboard for verifying raw OCR output from PDF."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_confirm_pdf"), callback_data=f"inv:pdf_ok:{doc_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}"
                )
            ],
        ]
    )


def get_store_selection_kb(
    doc_id: str, allowed_stores: Dict[str, str], default_store_id: Optional[str] = None
) -> InlineKeyboardMarkup:
    """Generates store selection keyboard with preferred workstation highlighted first."""
    rows = []

    # Place default store at the top if set
    if default_store_id and default_store_id in allowed_stores:
        def_name = allowed_stores[default_store_id]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"⭐ 🏢 {def_name} (По умолчанию)",
                    callback_data=f"inv:store:{doc_id}:{default_store_id}",
                )
            ]
        )

    other_stores = {
        sid: name for sid, name in allowed_stores.items() if sid != default_store_id
    }
    current_row = []
    for store_id, store_name in other_stores.items():
        current_row.append(
            InlineKeyboardButton(
                text=f"🏢 {store_name}", callback_data=f"inv:store:{doc_id}:{store_id}"
            )
        )
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)

    rows.append(
        [
            InlineKeyboardButton(
                text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_supplier_disambiguation_kb(
    doc_id: str, candidates: List[Dict[str, str]]
) -> InlineKeyboardMarkup:
    """Generates supplier disambiguation choices for identical INNs."""
    rows = []
    for c in candidates:
        dep = f" (цех {c['dept_codes']})" if c.get("dept_codes") else ""
        text = f"{c['name'][:30]}{dep}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=text, callback_data=f"inv:supp:{doc_id}:{c['id']}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_fuzzy_supplier_kb(
    doc_id: str, candidates: List[Dict[str, Any]]
) -> InlineKeyboardMarkup:
    """Generates fuzzy supplier selection choices based on catalog name matching."""
    rows = []
    for c in candidates:
        name = c["name"][:32]
        score = f"{c['score']:.0f}%"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{name} ({score})",
                    callback_data=f"inv:supp:{doc_id}:{c['id']}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_upload_confirmation_kb(doc_id: str) -> InlineKeyboardMarkup:
    """Generates final confirmation keyboard with pre-flight inspection option."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_create_draft"), callback_data=f"inv:upload:{doc_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_review_items"), callback_data=f"inv:review:{doc_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}"
                )
            ],
        ]
    )


def get_items_review_kb(
    doc_id: str, matched_items: List[Dict[str, Any]]
) -> InlineKeyboardMarkup:
    """Constructs line item review keyboard allowing inline edits before iiko upload."""
    rows = []
    for it in matched_items:
        num = it["num"]
        r_name = it["raw_name"][:16]
        i_name = it["iiko_name"][:16]
        coeff = float(it.get("coefficient", 1.0))
        c_str = f" x{coeff:g}" if coeff != 1.0 else ""
        btn_text = f"✏️ #{num}: {r_name} -> {i_name}{c_str}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=btn_text, callback_data=f"inv:edit:{doc_id}:{num}"
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text=t("btn_back_to_upload"), callback_data=f"inv:review_done:{doc_id}"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_setup_creds_kb(doc_id: str) -> InlineKeyboardMarkup:
    """Presents quick redirect button to configure iiko credentials."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_setup_iiko_creds"), callback_data="cab:set_creds"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}"
                )
            ],
        ]
    )


def get_upload_retry_kb(doc_id: str) -> InlineKeyboardMarkup:
    """Generates keyboard to retry failed iiko upload without destroying session."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_retry_upload"), callback_data=f"inv:upload:{doc_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}"
                )
            ],
        ]
    )


def get_packaging_coeff_kb(
    doc_id: str, item_idx: int, prod_id: str
) -> InlineKeyboardMarkup:
    """Generates explicit packaging multiplier choices including fractional and metric units."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="x1 (1 к 1)",
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:{prod_id}:1",
                ),
                InlineKeyboardButton(
                    text="x10",
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:{prod_id}:10",
                ),
                InlineKeyboardButton(
                    text="x20",
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:{prod_id}:20",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="x50",
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:{prod_id}:50",
                ),
                InlineKeyboardButton(
                    text="x100",
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:{prod_id}:100",
                ),
                InlineKeyboardButton(
                    text="x500",
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:{prod_id}:500",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_coeff_metric_gram"),
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:{prod_id}:0.001",
                ),
                InlineKeyboardButton(
                    text=t("btn_coeff_half"),
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:{prod_id}:0.5",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_custom_coeff"),
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:{prod_id}:custom",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}"
                ),
            ],
        ]
    )


def get_item_resolution_kb(
    doc_id: str, item_idx: int, candidates: List[Dict[str, Any]]
) -> InlineKeyboardMarkup:
    """Generates candidate choice buttons for an unknown raw item."""
    rows = []
    for c in candidates:
        name = c["name"][:35]
        score = f"{c['score']:.0f}%"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{name} ({score})",
                    callback_data=f"inv:match:{doc_id}:{item_idx}:{c['id']}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("btn_manual_sku"),
                callback_data=f"inv:manual:{doc_id}:{item_idx}",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("btn_skip_item"), callback_data=f"inv:skip:{doc_id}:{item_idx}"
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
