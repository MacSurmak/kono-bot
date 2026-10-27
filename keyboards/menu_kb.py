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
                text=t("cab_btn_default_store"), callback_data="cab:choose_store"
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


def get_default_store_selection_kb(
    stores: List[Dict[str, Any]], current_store_id: Optional[str]
) -> InlineKeyboardMarkup:
    """Constructs selection list for choosing user's primary restaurant branch."""
    rows = []
    for s in stores:
        s_id = s["store_id"]
        s_name = s["name"]
        prefix = "✅ " if s_id == current_store_id else "🏢 "
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix}{s_name}", callback_data=f"cab:store:{s_id}"
                )
            ]
        )

    if current_store_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("cab_btn_reset_store"), callback_data="cab:store:none"
                )
            ]
        )

    rows.append(
        [InlineKeyboardButton(text=t("menu_btn_back"), callback_data="menu:cabinet")]
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
            ]
        ]
    )


def get_user_mappings_kb(mappings: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Constructs revocation action list for operator's recent item alignments."""
    rows = []
    for m in mappings:
        m_id = m["id"]
        raw = m["raw_name"][:18]
        iiko = m["iiko_name"][:16]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"↩️ {raw} -> {iiko}", callback_data=f"cab:revoke:{m_id}"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text=t("menu_btn_back"), callback_data="menu:cabinet")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
