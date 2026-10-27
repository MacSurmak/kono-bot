from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from lexicon import t


from typing import List, Dict, Any, Optional


def get_admin_users_list_kb(
    users: List[Dict[str, Any]], page: int = 1, total_pages: int = 1
) -> InlineKeyboardMarkup:
    """Constructs paginated list of users allowing selection for role management."""
    rows = []
    for u in users:
        t_id = u["telegram_id"]
        name = u["full_name"][:20]
        badge = "👑 " if u["role"] == "admin" else "👤 "
        status = "" if u["is_active"] else " [БЛОК]"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{badge}{name}{status}",
                    callback_data=f"admin:user_card:{t_id}:{page}",
                )
            ]
        )

    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=f"admin:list_users:{page - 1}"
                )
            )
        else:
            nav_row.append(InlineKeyboardButton(text="⏹", callback_data="noop"))

        nav_row.append(
            InlineKeyboardButton(
                text=f"{page} / {total_pages}", callback_data="noop"
            )
        )

        if page < total_pages:
            nav_row.append(
                InlineKeyboardButton(
                    text="▶️", callback_data=f"admin:list_users:{page + 1}"
                )
            )
        else:
            nav_row.append(InlineKeyboardButton(text="⏹", callback_data="noop"))
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text=t("admin_btn_back"), callback_data="admin:back_main"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_user_manage_card_kb(
    target_id: int, current_role: str, is_active: bool, is_primary_admin: bool
) -> InlineKeyboardMarkup:
    """Constructs user management controls (role promotion/demotion, access toggle)."""
    rows = []
    if not is_primary_admin:
        if current_role == "admin":
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t("admin_btn_demote"),
                        callback_data=f"admin:set_role:{target_id}:operator",
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t("admin_btn_promote"),
                        callback_data=f"admin:set_role:{target_id}:admin",
                    )
                ]
            )

        if is_active:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t("admin_btn_block"),
                        callback_data=f"admin:set_active:{target_id}:0",
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=t("admin_btn_unblock"),
                        callback_data=f"admin:set_active:{target_id}:1",
                    )
                ]
            )

    rows.append(
        [
            InlineKeyboardButton(
                text=t("admin_btn_back_users"), callback_data="admin:list_users"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def get_training_accumulator_kb(
    batch_id: str, total_files: int
) -> InlineKeyboardMarkup:
    """Constructs live dashboard keyboard for accumulating training documents."""
    rows = []
    if total_files > 0:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("admin_btn_start_training_analysis"),
                    callback_data=f"admin:train_run:{batch_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("btn_cancel"),
                callback_data=f"admin:train_cancel:{batch_id}",
            )
        ]
    )
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


def get_admin_mappings_kb(
    results: list, query: str, page: int = 1, total_pages: int = 1
) -> InlineKeyboardMarkup:
    """Constructs paginated list of search results with deletion actions."""
    rows = []
    for r in results:
        btn_text = f"🗑 Удалить: {r['raw_name'][:20]} -> {r['iiko_name'][:18]}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=btn_text, callback_data=f"admin:del_map:{r['id']}"
                )
            ]
        )

    if total_pages > 1:
        import base64

        encoded_q = base64.urlsafe_b64encode(query.encode("utf-8")).decode("ascii")
        nav_row = []
        if page > 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="◀️",
                    callback_data=f"admin:del_map_p:{encoded_q}:{page - 1}",
                )
            )
        else:
            nav_row.append(InlineKeyboardButton(text="⏹", callback_data="noop"))

        nav_row.append(
            InlineKeyboardButton(
                text=f"{page} / {total_pages}", callback_data="noop"
            )
        )

        if page < total_pages:
            nav_row.append(
                InlineKeyboardButton(
                    text="▶️",
                    callback_data=f"admin:del_map_p:{encoded_q}:{page + 1}",
                )
            )
        else:
            nav_row.append(InlineKeyboardButton(text="⏹", callback_data="noop"))
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text=t("admin_btn_back"), callback_data="admin:back_main"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
