from typing import List, Dict, Any, Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from lexicon import t


def get_supplier_disambiguation_kb(
    doc_id: str, candidates: List[Dict[str, str]]
) -> InlineKeyboardMarkup:
    """Generates supplier disambiguation choices for identical INNs."""
    rows = []
    for c in candidates:
        dep = (
            t("btn_dept_code_fmt", dept=c["dept_codes"]) if c.get("dept_codes") else ""
        )
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
        score = t("btn_score_fmt", score=f"{c['score']:.0f}")
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
    doc_id: str,
    matched_items: List[Dict[str, Any]],
    page: int = 1,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    """Constructs paginated line item review keyboard allowing inline edits before iiko upload."""
    total_items = len(matched_items)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))

    start = (page - 1) * page_size
    current_slice = matched_items[start : start + page_size]

    rows = []
    for it in current_slice:
        num = it["num"]
        r_name = it["raw_name"][:16]
        i_name = it["iiko_name"][:16]
        coeff = float(it.get("coefficient", 1.0))
        c_str = t("btn_coeff_suffix_fmt", coeff=f"{coeff:g}") if coeff != 1.0 else ""
        btn_text = t(
            "btn_item_review_line",
            num=num,
            raw_name=r_name,
            iiko_name=i_name,
            coeff_str=c_str,
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=btn_text, callback_data=f"inv:edit:{doc_id}:{num}"
                )
            ]
        )

    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=f"inv:review_page:{doc_id}:{page - 1}"
                )
            )
        else:
            nav_row.append(InlineKeyboardButton(text="⏹", callback_data="noop"))

        nav_row.append(
            InlineKeyboardButton(text=f"{page} / {total_pages}", callback_data="noop")
        )

        if page < total_pages:
            nav_row.append(
                InlineKeyboardButton(
                    text="▶️", callback_data=f"inv:review_page:{doc_id}:{page + 1}"
                )
            )
        else:
            nav_row.append(InlineKeyboardButton(text="⏹", callback_data="noop"))
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text=t("btn_back_to_upload"), callback_data=f"inv:review_done:{doc_id}"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_invoice_store_choice_kb(
    doc_id: str,
    user_stores: List[Dict[str, Any]],
    page: int = 1,
    page_size: int = 5,
) -> InlineKeyboardMarkup:
    """Generates paginated store selection keyboard for incoming invoice."""
    total_items = len(user_stores)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))

    start = (page - 1) * page_size
    current_slice = user_stores[start : start + page_size]

    rows = []
    for s in current_slice:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("btn_store_choice_item", name=s["name"][:28]),
                    callback_data=f"inv:init_store:{doc_id}:{s['store_id']}",
                )
            ]
        )

    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=f"inv:store_page:{doc_id}:{page - 1}"
                )
            )
        else:
            nav_row.append(InlineKeyboardButton(text="⏹", callback_data="noop"))

        nav_row.append(
            InlineKeyboardButton(text=f"{page} / {total_pages}", callback_data="noop")
        )

        if page < total_pages:
            nav_row.append(
                InlineKeyboardButton(
                    text="▶️", callback_data=f"inv:store_page:{doc_id}:{page + 1}"
                )
            )
        else:
            nav_row.append(InlineKeyboardButton(text="⏹", callback_data="noop"))
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_setup_creds_kb(doc_id: str) -> InlineKeyboardMarkup:
    """Presents quick redirect buttons to configure iiko credentials or navigate back."""
    rows = [
        [
            InlineKeyboardButton(
                text=t("btn_setup_iiko_creds"), callback_data="cab:set_creds"
            )
        ],
        [
            InlineKeyboardButton(
                text=t("cab_btn_to_cabinet"), callback_data="menu:cabinet"
            ),
            InlineKeyboardButton(
                text=t("menu_btn_back"), callback_data="menu:back_main"
            ),
        ],
    ]
    if doc_id != "setup":
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def get_packaging_coeff_kb(doc_id: str, item_idx: int) -> InlineKeyboardMarkup:
    """Generates explicit packaging multiplier choices keeping callback_data well under 64-byte limit."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_coeff_preset_1"),
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:1",
                ),
                InlineKeyboardButton(
                    text=t("btn_coeff_preset_10"),
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:10",
                ),
                InlineKeyboardButton(
                    text=t("btn_coeff_preset_20"),
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:20",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_coeff_preset_50"),
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:50",
                ),
                InlineKeyboardButton(
                    text=t("btn_coeff_preset_100"),
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:100",
                ),
                InlineKeyboardButton(
                    text=t("btn_coeff_preset_500"),
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:500",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_coeff_metric_gram"),
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:0.001",
                ),
                InlineKeyboardButton(
                    text=t("btn_coeff_half"),
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:0.5",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_custom_coeff"),
                    callback_data=f"inv:coeff:{doc_id}:{item_idx}:custom",
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
