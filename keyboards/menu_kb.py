from typing import List, Dict, Any, Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from lexicon import t


def get_main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Constructs main interactive menu buttons."""
    buttons = [
        [
            InlineKeyboardButton(
                text=t("menu_btn_upload"), callback_data="menu:upload_info"
            )
        ],
        [
            InlineKeyboardButton(
                text=t("menu_btn_cabinet"), callback_data="menu:cabinet"
            )
        ],
        [InlineKeyboardButton(text=t("menu_btn_help"), callback_data="menu:help")],
    ]
    if is_admin:
        buttons.append(
            [InlineKeyboardButton(text=t("menu_btn_admin"), callback_data="admin:open")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cabinet_kb(has_creds: bool) -> InlineKeyboardMarkup:
    """Constructs user cabinet controls for managing iiko credentials and preferences."""
    rows = []
    if not has_creds:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("cab_btn_set_creds"), callback_data="cab:set_creds"
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("cab_btn_test_conn"), callback_data="cab:test_conn"
                ),
                InlineKeyboardButton(
                    text=t("cab_btn_change_creds"), callback_data="cab:set_creds"
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("cab_btn_clear_creds"), callback_data="cab:clear_creds"
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text=t("cab_btn_my_stores"), callback_data="cab:my_stores"
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("cab_btn_my_mappings"), callback_data="cab:my_mappings"
            )
        ]
    )
    rows.append(
        [InlineKeyboardButton(text=t("menu_btn_back"), callback_data="menu:back_main")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_user_stores_toggle_kb(
    all_stores: List[Dict[str, Any]],
    connected_store_ids: set,
    page: int = 1,
    page_size: int = 6,
) -> InlineKeyboardMarkup:
    """Constructs paginated store list allowing operators to toggle their workplace restaurants."""
    total_items = len(all_stores)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))

    start = (page - 1) * page_size
    current_slice = all_stores[start : start + page_size]

    rows = []
    for s in current_slice:
        s_id = s["id"]
        s_name = s["name"]
        is_conn = s_id in connected_store_ids
        prefix = t("checkbox_checked") if is_conn else t("checkbox_unchecked")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix}{s_name[:30]}",
                    callback_data=f"cab:toggle_store:{s_id}:{page}",
                )
            ]
        )

    # Pagination navigation bar
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=f"cab:my_stores:{page - 1}"
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
                    text="▶️", callback_data=f"cab:my_stores:{page + 1}"
                )
            )
        else:
            nav_row.append(InlineKeyboardButton(text="⏹", callback_data="noop"))
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text=t("cab_btn_to_cabinet"), callback_data="menu:cabinet"
            ),
            InlineKeyboardButton(
                text=t("menu_btn_back"), callback_data="menu:back_main"
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_cancel_input_kb() -> InlineKeyboardMarkup:
    """Constructs cancel button for active FSM input prompts."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_cancel"), callback_data="cab:cancel_input"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("menu_btn_back"), callback_data="menu:back_main"
                )
            ],
        ]
    )


def get_post_action_nav_kb() -> InlineKeyboardMarkup:
    """Constructs universal navigation footer preventing dead-end screens."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("menu_btn_upload"), callback_data="menu:upload_info"
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
    )


def get_user_mappings_kb(
    mappings: List[Dict[str, Any]], page: int, total_pages: int
) -> InlineKeyboardMarkup:
    """Constructs paginated revocation action list for operator's item alignments."""
    rows = []
    for m in mappings:
        m_id = m["id"]
        raw = m["raw_name"][:18]
        iiko = m["iiko_name"][:16]
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("btn_revoke_mapping_item", raw=raw, iiko=iiko),
                    callback_data=f"cab:revoke:{m_id}:{page}",
                )
            ]
        )

    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=f"cab:my_mappings:{page - 1}"
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
                    text="▶️", callback_data=f"cab:my_mappings:{page + 1}"
                )
            )
        else:
            nav_row.append(InlineKeyboardButton(text="⏹", callback_data="noop"))
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text=t("cab_btn_to_cabinet"), callback_data="menu:cabinet"
            ),
            InlineKeyboardButton(
                text=t("menu_btn_back"), callback_data="menu:back_main"
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
