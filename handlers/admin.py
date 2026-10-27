import re
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from loguru import logger

from config import cfg
from iiko_client import client
from keyboards.admin_kb import (
    get_admin_main_kb,
    get_admin_stores_kb,
    get_iiko_import_stores_kb,
    get_admin_mappings_kb,
)
from storage import (
    create_invite_token,
    get_all_bot_users,
    get_all_managed_stores,
    add_managed_store,
    delete_managed_store,
    search_mappings_for_admin,
    delete_mapping_by_id,
)
from lexicon import t


class AdminState(StatesGroup):
    waiting_search_mapping = State()
    waiting_manual_store = State()


from config import get_admin_ids

router = Router(name="admin_router")
get_configured_admin_ids = get_admin_ids


@router.message(Command("admin"))
async def handle_admin_panel(message: types.Message):
    """Entrypoint to admin panel for privileged operators."""
    if message.from_user.id not in get_configured_admin_ids():
        return

    await message.answer(
        t("admin_panel_title"), reply_markup=get_admin_main_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:open")
async def process_admin_open_callback(callback: types.CallbackQuery):
    """Opens admin panel from main interactive menu button."""
    if callback.from_user.id not in get_configured_admin_ids():
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    await callback.message.edit_text(
        t("admin_panel_title"), reply_markup=get_admin_main_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:create_invite")
async def process_create_invite(callback: types.CallbackQuery):
    """Generates secure one-time invite deep-link."""
    if callback.from_user.id not in get_configured_admin_ids():
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
    """Displays active registered users."""
    if callback.from_user.id not in get_configured_admin_ids():
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    users = await get_all_bot_users()
    if not users:
        await callback.message.answer(t("admin_users_empty"))
        return

    lines = [t("admin_users_title")]
    for idx, u in enumerate(users, 1):
        username_str = f"(@{u['username']})" if u["username"] else ""
        role_badge = "👑 [Админ]" if u["role"] == "admin" else "👤 [Оператор]"
        lines.append(
            f"{idx}. {role_badge} <b>{u['full_name']}</b> {username_str} — ID: <code>{u['telegram_id']}</code>"
        )

    await callback.message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data == "admin:back_main")
async def process_back_main(callback: types.CallbackQuery, state: FSMContext):
    """Returns to admin main menu."""
    if callback.from_user.id not in get_configured_admin_ids():
        return
    await state.clear()
    await callback.message.edit_text(
        t("admin_panel_title"), reply_markup=get_admin_main_kb(), parse_mode="HTML"
    )


# ================= STORE MANAGEMENT HANDLERS =================
@router.callback_query(F.data == "admin:manage_stores")
async def process_manage_stores(callback: types.CallbackQuery, state: FSMContext):
    """Displays active managed stores with deletion controls."""
    if callback.from_user.id not in get_configured_admin_ids():
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    await state.clear()
    stores = await get_all_managed_stores()
    if not stores:
        text = t("admin_stores_empty")
    else:
        text = t("admin_stores_title") + "\n".join(
            f"• <b>{s['name']}</b> (<code>{s['store_id']}</code>)" for s in stores
        )

    await callback.message.edit_text(
        text, reply_markup=get_admin_stores_kb(stores), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin:del_st:"))
async def process_delete_store(callback: types.CallbackQuery):
    """Removes a store from active managed list."""
    if callback.from_user.id not in get_configured_admin_ids():
        return
    store_id = callback.data.split(":")[2]
    await delete_managed_store(store_id)
    logger.info(f"Admin {callback.from_user.id} removed store {store_id}")
    await callback.answer(t("admin_store_deleted_success"), show_alert=True)

    stores = await get_all_managed_stores()
    text = t("admin_stores_title") + "\n".join(
        f"• <b>{s['name']}</b> (<code>{s['store_id']}</code>)" for s in stores
    )
    await callback.message.edit_text(
        text, reply_markup=get_admin_stores_kb(stores), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin:add_st:"))
async def process_add_store_menu(callback: types.CallbackQuery):
    """Fetches candidate stores from /api/corporation/stores with pagination."""
    if callback.from_user.id not in get_configured_admin_ids():
        return

    page = int(callback.data.split(":")[2])
    managed_stores = await get_all_managed_stores()
    existing_store_ids = {s["store_id"] for s in managed_stores}
    iiko_stores = client.get_iiko_departments()
    available_to_add = [d for d in iiko_stores if d["id"] not in existing_store_ids]

    if available_to_add:
        await callback.message.edit_text(
            t("admin_iiko_stores_available"),
            reply_markup=get_iiko_import_stores_kb(available_to_add, page=page),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            t("admin_iiko_no_new_stores"),
            reply_markup=get_iiko_import_stores_kb([], page=0),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("admin:st_add:"))
async def process_store_import(callback: types.CallbackQuery):
    """Adds a store discovered from iiko API to managed stores using safe ID lookup."""
    if callback.from_user.id not in get_configured_admin_ids():
        return
    store_id = callback.data.split(":")[2]
    iiko_stores = client.get_iiko_departments()
    store = next((s for s in iiko_stores if s["id"] == store_id), None)
    name = store["name"] if store else "Склад iiko"

    await add_managed_store(store_id, name)
    logger.info(
        f"Admin {callback.from_user.id} imported store from iiko: {name} ({store_id})"
    )
    await callback.answer(t("admin_store_added_success", name=name), show_alert=True)

    stores = await get_all_managed_stores()
    text = t("admin_stores_title") + "\n".join(
        f"• <b>{s['name']}</b> (<code>{s['store_id']}</code>)" for s in stores
    )
    await callback.message.edit_text(
        text, reply_markup=get_admin_stores_kb(stores), parse_mode="HTML"
    )


@router.callback_query(F.data == "admin:manual_store_prompt")
async def process_manual_store_prompt(callback: types.CallbackQuery, state: FSMContext):
    """Sets FSM state waiting for manual store UUID and name."""
    if callback.from_user.id not in get_configured_admin_ids():
        return
    await state.set_state(AdminState.waiting_manual_store)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("admin_btn_back"), callback_data="admin:manage_stores"
                )
            ]
        ]
    )
    await callback.message.edit_text(
        t("admin_store_manual_prompt"), reply_markup=cancel_kb, parse_mode="HTML"
    )


@router.message(AdminState.waiting_manual_store)
async def handle_manual_store_input(message: types.Message, state: FSMContext):
    """Parses and registers manually entered store GUID and name."""
    if message.from_user.id not in get_configured_admin_ids():
        return
    text = message.text.strip()
    parts = text.split(maxsplit=1)

    if len(parts) != 2 or len(parts[0]) < 32:
        await message.answer(t("admin_store_invalid_format"))
        return

    store_id, name = parts[0].strip(), parts[1].strip()
    await add_managed_store(store_id, name)
    logger.info(
        f"Admin {message.from_user.id} manually added store: {name} ({store_id})"
    )
    await state.clear()
    await message.answer(t("admin_store_added_success", name=name), parse_mode="HTML")


# ================= KNOWLEDGE BASE MAPPING REMOVAL HANDLERS =================
@router.callback_query(F.data == "admin:manage_mappings")
async def process_manage_mappings(callback: types.CallbackQuery, state: FSMContext):
    """Prompts admin for search query to locate incorrect mappings."""
    if callback.from_user.id not in get_configured_admin_ids():
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
    if message.from_user.id not in get_configured_admin_ids():
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
    if callback.from_user.id not in get_configured_admin_ids():
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
