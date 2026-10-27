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
        [
            InlineKeyboardButton(
                text=t("menu_btn_help"), callback_data="menu:help"
            )
        ],
    ]
    if is_admin:
        buttons.append([
            InlineKeyboardButton(
                text=t("menu_btn_admin"), callback_data="admin:open"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
