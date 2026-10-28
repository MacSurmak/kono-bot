import asyncio
from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from loguru import logger

from lexicon import t
from services.iiko_client import client
from services.crypto import encrypt_secret, decrypt_secret
from config import get_admin_ids
from storage import (
    get_bot_user,
    update_user_iiko_credentials,
    get_user_stores,
    toggle_user_store,
    get_user_mappings,
    revoke_user_mapping,
)
from keyboards.menu_kb import (
    get_main_menu_kb,
    get_cabinet_kb,
    get_user_stores_toggle_kb,
    get_cancel_input_kb,
    get_user_mappings_kb,
)
from keyboards.invoices_kb import get_setup_creds_kb

router = Router(name="menu_router")


class UserCabinetState(StatesGroup):
    waiting_iiko_login = State()
    waiting_iiko_password = State()


@router.callback_query(F.data == "menu:back_main")
async def process_back_main_menu(callback: types.CallbackQuery, state: FSMContext):
    """Returns operator to top-level interactive navigation menu."""
    await state.clear()
    is_admin = callback.from_user.id in get_admin_ids()
    await callback.message.edit_text(
        t("menu_main_title"),
        reply_markup=get_main_menu_kb(is_admin=is_admin),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:upload_info")
async def process_upload_info(callback: types.CallbackQuery):
    """Explains invoice upload workflow to operator."""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("menu_btn_back"), callback_data="menu:back_main"
                )
            ]
        ]
    )
    await callback.message.edit_text(
        t("menu_upload_info_text"), reply_markup=kb, parse_mode="HTML"
    )


@router.callback_query(F.data == "menu:help")
async def process_menu_help(callback: types.CallbackQuery):
    """Displays user assistance manual with return button."""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("menu_btn_back"), callback_data="menu:back_main"
                )
            ]
        ]
    )
    await callback.message.edit_text(t("help_text"), reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "menu:cabinet")
async def process_open_cabinet(callback: types.CallbackQuery, state: FSMContext):
    """Displays operator profile, credential status, and default restaurant."""
    await state.clear()
    user_id = callback.from_user.id
    user = await get_bot_user(user_id)
    if not user:
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    has_creds = bool(user.get("iiko_login") and user.get("iiko_password_encrypted"))
    creds_status = (
        t("cab_creds_bound", login=user["iiko_login"])
        if has_creds
        else t("cab_creds_not_configured")
    )

    user_stores = await get_user_stores(user_id)
    stores_str = (
        ", ".join(s["name"] for s in user_stores)
        if user_stores
        else t("cab_no_stores_connected")
    )

    role_str = t("role_admin") if user.get("role") == "admin" else t("role_operator")

    text = t(
        "cab_profile_card",
        full_name=user.get("full_name") or t("profile_default_name"),
        username=(
            f"@{user['username']}" if user.get("username") else t("user_no_username")
        ),
        role=role_str,
        creds_status=creds_status,
        default_store=stores_str,
    )
    await callback.message.edit_text(
        text, reply_markup=get_cabinet_kb(has_creds=has_creds), parse_mode="HTML"
    )


@router.callback_query(F.data == "cab:set_creds")
async def process_start_credential_input(
    callback: types.CallbackQuery, state: FSMContext
):
    """Prompts operator for personal iikoOffice login and records prompt message ID."""
    await state.set_state(UserCabinetState.waiting_iiko_login)
    msg = await callback.message.edit_text(
        t("cab_prompt_login"),
        reply_markup=get_cancel_input_kb(),
        parse_mode="HTML",
    )
    await state.update_data(prompt_msg_id=msg.message_id)


@router.message(UserCabinetState.waiting_iiko_login)
async def process_login_input(message: types.Message, state: FSMContext):
    """Records login, purges previous prompt, and prompts operator for password at bottom."""
    login = message.text.strip()
    data = await state.get_data()
    prompt_id = data.get("prompt_msg_id")

    if len(login) < 2:
        await message.answer(t("cab_invalid_login"), reply_markup=get_cancel_input_kb())
        return

    if prompt_id:
        try:
            await message.bot.delete_message(
                chat_id=message.chat.id, message_id=prompt_id
            )
        except Exception:
            pass

    await state.set_state(UserCabinetState.waiting_iiko_password)
    pwd_msg = await message.answer(
        t("cab_prompt_password"),
        reply_markup=get_cancel_input_kb(),
        parse_mode="HTML",
    )
    await state.update_data(iiko_login=login, prompt_msg_id=pwd_msg.message_id)


@router.message(UserCabinetState.waiting_iiko_password)
async def process_password_input(message: types.Message, state: FSMContext):
    """Validates credentials against iiko, encrypts password, and purges previous prompt."""
    password = message.text.strip()

    # Immediate chat hygiene: destroy plaintext password message
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message with password: {e}")

    data = await state.get_data()
    login = data.get("iiko_login")
    prompt_id = data.get("prompt_msg_id")
    await state.clear()

    if prompt_id:
        try:
            await message.bot.delete_message(
                chat_id=message.chat.id, message_id=prompt_id
            )
        except Exception:
            pass

    if not login or not password:
        await message.answer(t("cab_creds_empty"))
        return

    status_msg = await message.answer(t("cab_validating_wait"))

    try:
        # Validate credentials directly with iiko server
        await asyncio.to_thread(client.test_user_credentials, login, password)

        # Encrypt password using master Fernet key before persisting
        encrypted_pass = encrypt_secret(password)
        await update_user_iiko_credentials(message.from_user.id, login, encrypted_pass)

        logger.info(
            f"User {message.from_user.id} (@{message.from_user.username}) successfully bound iiko account: '{login}'"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("cab_btn_to_cabinet"), callback_data="menu:cabinet"
                    )
                ]
            ]
        )
        await status_msg.edit_text(
            t("cab_creds_success", login=login),
            reply_markup=kb,
            parse_mode="HTML",
        )

    except Exception as e:
        logger.warning(f"Failed iiko credential authentication for '{login}': {e}")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("cab_btn_retry"), callback_data="cab:set_creds"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=t("cab_btn_to_cabinet"), callback_data="menu:cabinet"
                    )
                ],
            ]
        )
        await status_msg.edit_text(
            t("cab_creds_failed", error=str(e)),
            reply_markup=kb,
            parse_mode="HTML",
        )


@router.callback_query(F.data == "cab:test_conn")
async def process_test_connection(callback: types.CallbackQuery):
    """Executes live test authentication using encrypted user credentials."""
    user = await get_bot_user(callback.from_user.id)
    if (
        not user
        or not user.get("iiko_login")
        or not user.get("iiko_password_encrypted")
    ):
        await callback.answer(t("cab_no_creds_alert"), show_alert=True)
        return

    login = user["iiko_login"]
    try:
        password = decrypt_secret(user["iiko_password_encrypted"])
        await asyncio.to_thread(client.test_user_credentials, login, password)
        await callback.answer(t("cab_test_ok_alert"), show_alert=True)
    except Exception as e:
        await callback.answer(
            t("cab_test_fail_alert", error=str(e)[:100]), show_alert=True
        )


@router.callback_query(F.data.startswith("cab:my_mappings"))
async def process_view_my_mappings(callback: types.CallbackQuery):
    """Displays operator's item alignments across all time with pagination."""
    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 1
    page_size = 6
    offset = (page - 1) * page_size
    mappings, total_count = await get_user_mappings(
        callback.from_user.id, offset=offset, limit=page_size
    )

    if not mappings and page == 1:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("menu_btn_back"), callback_data="menu:cabinet"
                    )
                ]
            ]
        )
        await callback.message.edit_text(
            t("cab_my_mappings_empty"), reply_markup=kb, parse_mode="HTML"
        )
        return

    total_pages = max(1, (total_count + page_size - 1) // page_size)
    await callback.message.edit_text(
        t("cab_my_mappings_title"),
        reply_markup=get_user_mappings_kb(mappings, page=page, total_pages=total_pages),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("cab:revoke:"))
async def process_revoke_my_mapping(callback: types.CallbackQuery):
    """Revokes single mapping created by operator without breaking shared dictionary."""
    parts = callback.data.split(":")
    audit_id = int(parts[2])
    current_page = int(parts[3]) if len(parts) > 3 else 1

    success = await revoke_user_mapping(callback.from_user.id, audit_id)
    if success:
        logger.info(
            f"Operator {callback.from_user.id} revoked mapping audit log #{audit_id}"
        )
        await callback.answer(t("cab_mapping_revoked_success"), show_alert=True)
    else:
        await callback.answer(t("cab_mapping_revoke_failed"), show_alert=True)

    callback.data = f"cab:my_mappings:{current_page}"
    await process_view_my_mappings(callback)


@router.callback_query(F.data == "cab:clear_creds")
async def process_clear_credentials(callback: types.CallbackQuery, state: FSMContext):
    """Unbinds personal iiko credentials and purges cached session token."""
    user = await get_bot_user(callback.from_user.id)
    if user and user.get("iiko_login"):
        client.invalidate_user_token(user["iiko_login"])

    await update_user_iiko_credentials(callback.from_user.id, None, None)
    logger.info(f"User {callback.from_user.id} cleared iiko credentials.")
    await callback.answer(t("cab_creds_cleared"), show_alert=True)
    await process_open_cabinet(callback, state)


@router.callback_query(F.data.startswith("cab:my_stores"))
async def process_view_my_stores(callback: types.CallbackQuery):
    """Displays paginated interactive toggle list of iikoChain restaurants for operator."""
    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 1

    user = await get_bot_user(callback.from_user.id)
    if (
        not user
        or not user.get("iiko_login")
        or not user.get("iiko_password_encrypted")
    ):
        await callback.message.edit_text(
            t("invoice_no_creds_error"),
            reply_markup=get_setup_creds_kb("setup"),
            parse_mode="HTML",
        )
        return

    login = user["iiko_login"]
    try:
        password = decrypt_secret(user["iiko_password_encrypted"])
    except Exception:
        await callback.answer(t("cab_creds_empty"), show_alert=True)
        return

    try:
        stores = await asyncio.to_thread(
            client.get_iiko_departments_for_user, login, password
        )
    except Exception as e:
        await callback.answer(t("cab_iiko_conn_error", error=str(e)[:100]), show_alert=True)
        return

    if not stores:
        await callback.answer(
            t("cab_no_stores_found"), show_alert=True
        )
        return

    user_stores = await get_user_stores(callback.from_user.id)
    connected_ids = {s["store_id"] for s in user_stores}

    await callback.message.edit_text(
        t("cab_my_stores_title"),
        reply_markup=get_user_stores_toggle_kb(
            stores, connected_ids, page=page, page_size=6
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("cab:toggle_store:"))
async def process_toggle_store(callback: types.CallbackQuery):
    """Toggles restaurant connection state for operator maintaining current page."""
    parts = callback.data.split(":")
    store_id = parts[2]
    current_page = int(parts[3]) if len(parts) > 3 else 1

    user = await get_bot_user(callback.from_user.id)
    if (
        not user
        or not user.get("iiko_login")
        or not user.get("iiko_password_encrypted")
    ):
        return

    login = user["iiko_login"]
    password = decrypt_secret(user["iiko_password_encrypted"])
    stores = await asyncio.to_thread(
        client.get_iiko_departments_for_user, login, password
    )
    target_store = next((s for s in stores if s["id"] == store_id), None)
    target_name = target_store["name"] if target_store else t("store_default_fallback")

    is_connected = await toggle_user_store(callback.from_user.id, store_id, target_name)

    msg = (
        t("cab_store_connected", store=target_name)
        if is_connected
        else t("cab_store_disconnected", store=target_name)
    )
    await callback.answer(msg)

    callback.data = f"cab:my_stores:{current_page}"
    await process_view_my_stores(callback)


@router.callback_query(F.data == "cab:cancel_input")
async def process_cancel_input(callback: types.CallbackQuery, state: FSMContext):
    """Aborts credential input and returns to cabinet."""
    await state.clear()
    await process_open_cabinet(callback, state)


@router.callback_query(F.data == "noop")
async def process_noop(callback: types.CallbackQuery):
    """Silently handles non-interactive pagination indicator clicks."""
    await callback.answer()
