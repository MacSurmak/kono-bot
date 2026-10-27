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
            [
                InlineKeyboardButton(
                    text=t("admin_btn_training"), callback_data="admin:training_menu"
                )
            ],
        ]
    )


def get_training_accumulator_kb(batch_id: str, total_files: int) -> InlineKeyboardMarkup:
    """Constructs live dashboard keyboard for accumulating training documents."""
    rows = []
    if total_files > 0:
        rows.append([
            InlineKeyboardButton(
                text=t("admin_btn_start_training_analysis"),
                callback_data=f"admin:train_run:{batch_id}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text=t("btn_cancel"),
            callback_data=f"admin:train_cancel:{batch_id}",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_training_confirmation_kb(batch_id: str, new_count: int) -> InlineKeyboardMarkup:
    """Constructs final commit confirmation buttons after dry-run simulation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("admin_btn_commit_training", count=new_count),
                    callback_data=f"admin:train_commit:{batch_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin_btn_download_report"),
                    callback_data=f"admin:train_report:{batch_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_cancel"),
                    callback_data=f"admin:train_cancel:{batch_id}",
                )
            ],
        ]
    )


def get_admin_stores_kb(stores: list) -> InlineKeyboardMarkup:
    """Constructs list of managed stores with delete options."""
    rows = []
    for s in stores:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🏢 {s['name'][:24]}", callback_data="admin:noop"
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить", callback_data=f"admin:del_st:{s['store_id']}"
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("admin_btn_add_store"), callback_data="admin:add_st:0"
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("admin_btn_back"), callback_data="admin:back_main"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_iiko_import_stores_kb(
    available_stores: list, page: int = 0, page_size: int = 6
) -> InlineKeyboardMarkup:
    """Constructs paginated selection buttons for adding stores discovered from iiko API."""
    total = len(available_stores)
    start = page * page_size
    end = start + page_size
    current_page_items = available_stores[start:end]

    rows = []
    for s in current_page_items:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"➕ {s['name'][:32]}", callback_data=f"admin:st_add:{s['id']}"
                )
            ]
        )

    nav_row = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️ Назад", callback_data=f"admin:add_st:{page - 1}"
            )
        )
    if end < total:
        nav_row.append(
            InlineKeyboardButton(
                text="Вперед ➡️", callback_data=f"admin:add_st:{page + 1}"
            )
        )
    if nav_row:
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text=t("admin_btn_manual_store"),
                callback_data="admin:manual_store_prompt",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("admin_btn_back"), callback_data="admin:manage_stores"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_admin_mappings_kb(results: list) -> InlineKeyboardMarkup:
    """Constructs list of search results with deletion actions."""
    rows = []
    for r in results:
        btn_text = f"🗑 Удалить: {r['raw_name'][:24]} -> {r['iiko_name'][:20]}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=btn_text, callback_data=f"admin:del_map:{r['id']}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("admin_btn_back"), callback_data="admin:back_main"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
