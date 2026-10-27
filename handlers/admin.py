import re
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from loguru import logger

from config import cfg
from services.iiko_client import client
from keyboards.admin_kb import (
    get_admin_main_kb,
    get_admin_mappings_kb,
)
from storage import (
    create_invite_token,
    get_all_bot_users,
    get_bot_user,
    set_user_role,
    set_user_active,
    is_admin_user,
    search_mappings_for_admin,
    delete_mapping_by_id,
)
from lexicon import t


class AdminState(StatesGroup):
    waiting_search_mapping = State()
    waiting_manual_store = State()


router = Router(name="admin_router")


@router.message(Command("admin"))
async def handle_admin_panel(message: types.Message):
    """Entrypoint to admin panel for privileged operators."""
    if not await is_admin_user(message.from_user.id):
        return

    await message.answer(
        t("admin_panel_title"), reply_markup=get_admin_main_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:open")
async def process_admin_open_callback(callback: types.CallbackQuery):
    """Opens admin panel from main interactive menu button."""
    if not await is_admin_user(callback.from_user.id):
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    await callback.message.edit_text(
        t("admin_panel_title"), reply_markup=get_admin_main_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:create_invite")
async def process_create_invite(callback: types.CallbackQuery):
    """Generates secure one-time invite deep-link."""
    if not await is_admin_user(callback.from_user.id):
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    from loguru import logger

    bot_info = await callback.bot.get_me()
    token = await create_invite_token(created_by=callback.from_user.id)
    invite_url = f"https://t.me/{bot_info.username}?start=inv_{token}"

    logger.info(f"Admin {callback.from_user.id} generated a new invite token: {token}")
    await callback.message.answer(
        t("admin_invite_created", invite_url=invite_url), parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:list_users")
async def process_list_users(callback: types.CallbackQuery):
    """Displays active registered users as interactive inline list."""
    if not await is_admin_user(callback.from_user.id):
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    users = await get_all_bot_users()
    if not users:
        await callback.message.edit_text(t("admin_users_empty"))
        return

    from keyboards.admin_kb import get_admin_users_list_kb

    await callback.message.edit_text(
        t("admin_users_title"),
        reply_markup=get_admin_users_list_kb(users),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin:user_card:"))
async def process_view_user_card(callback: types.CallbackQuery):
    """Presents management card for single employee."""
    if not await is_admin_user(callback.from_user.id):
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    target_id = int(callback.data.split(":")[2])
    target_user = await get_bot_user(target_id)
    if not target_user:
        await callback.answer(t("admin_users_empty"), show_alert=True)
        return

    from keyboards.admin_kb import get_user_manage_card_kb
    from storage import get_all_managed_stores
    from config import get_admin_ids

    from storage import get_user_stores

    is_primary = target_id in get_admin_ids()
    user_stores = await get_user_stores(target_id)
    stores_str = (
        ", ".join(s["name"] for s in user_stores)
        if user_stores
        else "Нет подключенных точек"
    )

    role_str = "👑 Администратор" if target_user["role"] == "admin" else "👤 Оператор"
    status_str = "🟢 Активен" if target_user["is_active"] else "🔴 Заблокирован"
    login_str = target_user.get("iiko_login") or "Не настроен"

    text = t(
        "admin_user_card_title",
        full_name=target_user["full_name"],
        username=(
            f"@{target_user['username']}"
            if target_user.get("username")
            else "Без юзернейма"
        ),
        telegram_id=target_user["telegram_id"],
        role_str=role_str,
        status_str=status_str,
        iiko_login=login_str,
        default_store=stores_str,
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_user_manage_card_kb(
            target_id=target_id,
            current_role=target_user["role"],
            is_active=target_user["is_active"],
            is_primary_admin=is_primary,
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin:set_role:"))
async def process_change_user_role(callback: types.CallbackQuery):
    """Promotes or demotes user role in database."""
    if not await is_admin_user(callback.from_user.id):
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    parts = callback.data.split(":")
    target_id, new_role = int(parts[2]), parts[3]

    from config import get_admin_ids

    if target_id in get_admin_ids() and new_role != "admin":
        await callback.answer(t("admin_cannot_modify_primary"), show_alert=True)
        return

    await set_user_role(target_id, new_role)
    logger.info(
        f"Admin {callback.from_user.id} changed user {target_id} role to '{new_role}'"
    )
    await callback.answer(t("admin_role_updated"), show_alert=True)
    await process_view_user_card(callback)


@router.callback_query(F.data.startswith("admin:set_active:"))
async def process_toggle_user_active(callback: types.CallbackQuery):
    """Blocks or activates employee account."""
    if not await is_admin_user(callback.from_user.id):
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    parts = callback.data.split(":")
    target_id, is_active_val = int(parts[2]), bool(int(parts[3]))

    from config import get_admin_ids

    if target_id in get_admin_ids() and not is_active_val:
        await callback.answer(t("admin_cannot_modify_primary"), show_alert=True)
        return

    await set_user_active(target_id, is_active_val)
    logger.info(
        f"Admin {callback.from_user.id} changed user {target_id} is_active to {is_active_val}"
    )
    await callback.answer(t("admin_status_updated"), show_alert=True)
    await process_view_user_card(callback)


@router.callback_query(F.data == "admin:back_main")
async def process_back_main(callback: types.CallbackQuery, state: FSMContext):
    """Returns to admin main menu."""
    if not await is_admin_user(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text(
        t("admin_panel_title"), reply_markup=get_admin_main_kb(), parse_mode="HTML"
    )


# ================= KNOWLEDGE BASE MAPPING REMOVAL HANDLERS =================
@router.callback_query(F.data == "admin:manage_mappings")
async def process_manage_mappings(callback: types.CallbackQuery, state: FSMContext):
    """Prompts admin for search query to locate incorrect mappings."""
    if not await is_admin_user(callback.from_user.id):
        return
    await state.set_state(AdminState.waiting_search_mapping)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("admin_btn_back"), callback_data="admin:back_main"
                )
            ]
        ]
    )
    await callback.message.edit_text(
        t("admin_search_mapping_prompt"), reply_markup=cancel_kb, parse_mode="HTML"
    )


@router.message(AdminState.waiting_search_mapping)
async def handle_search_mapping_input(message: types.Message, state: FSMContext):
    """Executes search and presents candidates for deletion."""
    if not await is_admin_user(message.from_user.id):
        return
    query = message.text.strip()
    results = await search_mappings_for_admin(query, limit=8)

    if not results:
        await message.answer(t("admin_search_mapping_empty", query=query))
        return

    await state.clear()
    await message.answer(
        t("admin_search_mapping_results", count=len(results)),
        reply_markup=get_admin_mappings_kb(results),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin:del_map:"))
async def process_delete_mapping(callback: types.CallbackQuery):
    """Permanently deletes chosen mapping record from knowledge base."""
    if not await is_admin_user(callback.from_user.id):
        return
    mapping_id = int(callback.data.split(":")[2])
    success = await delete_mapping_by_id(mapping_id)
    if success:
        logger.info(
            f"Admin {callback.from_user.id} deleted mapping #{mapping_id} from knowledge base"
        )
        await callback.answer(t("admin_mapping_deleted_success"), show_alert=True)
    await callback.message.edit_text(
        t("admin_panel_title"), reply_markup=get_admin_main_kb(), parse_mode="HTML"
    )
