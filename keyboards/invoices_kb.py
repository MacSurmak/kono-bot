from typing import List, Dict, Any
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from lexicon import t
from config import ALLOWED_STORES


def get_store_selection_kb(doc_id: str) -> InlineKeyboardMarkup:
    """Generates store selection keyboard bound strictly to ALLOWED_STORES."""
    buttons = []
    for store_id, store_name in ALLOWED_STORES.items():
        buttons.append(
            InlineKeyboardButton(
                text=f"🏢 {store_name}",
                callback_data=f"inv:store:{doc_id}:{store_id}"
            )
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            buttons,
            [InlineKeyboardButton(text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}")]
        ]
    )


def get_supplier_disambiguation_kb(
    doc_id: str, candidates: List[Dict[str, str]]
) -> InlineKeyboardMarkup:
    """Generates supplier disambiguation choices for identical INNs."""
    rows = []
    for c in candidates:
        dep = f" (цех {c['dept_codes']})" if c["dept_codes"] else ""
        text = f"{c['name'][:30]}{dep}"
        rows.append([
            InlineKeyboardButton(
                text=text,
                callback_data=f"inv:supp:{doc_id}:{c['id']}"
            )
        ])
    rows.append([InlineKeyboardButton(text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_upload_confirmation_kb(doc_id: str) -> InlineKeyboardMarkup:
    """Generates final confirmation keyboard for uploading to iiko."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_create_draft"),
                    callback_data=f"inv:upload:{doc_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_cancel"),
                    callback_data=f"inv:cancel:{doc_id}"
                )
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
        rows.append([
            InlineKeyboardButton(
                text=f"{name} ({score})",
                callback_data=f"inv:match:{doc_id}:{item_idx}:{c['id']}"
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text=t("btn_skip_item"),
            callback_data=f"inv:skip:{doc_id}:{item_idx}"
        )
    ])
    rows.append([
        InlineKeyboardButton(
            text=t("btn_cancel"),
            callback_data=f"inv:cancel:{doc_id}"
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
