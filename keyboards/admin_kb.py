from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from lexicon import t


def get_admin_main_kb() -> InlineKeyboardMarkup:
    """Constructs admin control panel inline buttons without hardcoded text."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("admin_btn_invite"), callback_data="admin:create_invite"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin_btn_users"), callback_data="admin:list_users"
                )
            ],
        ]
    )
