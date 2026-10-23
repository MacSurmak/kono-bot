from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_admin_main_kb() -> InlineKeyboardMarkup:
    """Constructs admin control panel inline buttons."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎟 Создать ссылку-приглашение", callback_data="admin:create_invite"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Список пользователей", callback_data="admin:list_users"
                )
            ],
        ]
    )
