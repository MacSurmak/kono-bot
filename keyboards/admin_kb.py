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
            [
                InlineKeyboardButton(
                    text=t("admin_btn_stores"), callback_data="admin:manage_stores"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin_btn_mappings"), callback_data="admin:manage_mappings"
                )
            ],
        ]
    )


def get_admin_stores_kb(stores: list) -> InlineKeyboardMarkup:
    """Constructs list of managed stores with delete options."""
    rows = []
    for s in stores:
        rows.append([
            InlineKeyboardButton(text=f"🏢 {s['name']}", callback_data=f"admin:noop"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin:del_store:{s['store_id']}"),
        ])
    rows.append([
        InlineKeyboardButton(text=t("admin_btn_add_store"), callback_data="admin:add_store")
    ])
    rows.append([
        InlineKeyboardButton(text=t("admin_btn_back"), callback_data="admin:back_main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_iiko_import_stores_kb(available_stores: list) -> InlineKeyboardMarkup:
    """Constructs selection buttons for adding stores discovered from iiko API."""
    rows = []
    for s in available_stores[:8]:
        rows.append([
            InlineKeyboardButton(
                text=f"➕ {s['name'][:30]}",
                callback_data=f"admin:store_import:{s['id']}:{s['name'][:25]}"
            )
        ])
    rows.append([
        InlineKeyboardButton(text=t("admin_btn_manual_store"), callback_data="admin:manual_store_prompt")
    ])
    rows.append([
        InlineKeyboardButton(text=t("admin_btn_back"), callback_data="admin:manage_stores")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_admin_mappings_kb(results: list) -> InlineKeyboardMarkup:
    """Constructs list of search results with deletion actions."""
    rows = []
    for r in results:
        btn_text = f"🗑 Удалить: {r['raw_name'][:24]} -> {r['iiko_name'][:20]}"
        rows.append([
            InlineKeyboardButton(text=btn_text, callback_data=f"admin:del_map:{r['id']}")
        ])
    rows.append([
        InlineKeyboardButton(text=t("admin_btn_back"), callback_data="admin:back_main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
