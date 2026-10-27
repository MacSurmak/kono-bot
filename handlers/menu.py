import asyncio
from aiogram import Router, types, F
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
)
from keyboards.menu_kb import (
    get_main_menu_kb,
    get_cabinet_kb,
    get_user_stores_toggle_kb,
    get_cancel_input_kb,
    get_user_mappings_kb,
)

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
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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
        f"<code>{user['iiko_login']}</code> (✅ привязан)"
        if has_creds
        else "<i>❌ Не настроен</i>"
    )

    from storage import get_user_stores
    user_stores = await get_user_stores(user_id)
    stores_str = ", ".join(s["name"] for s in user_stores) if user_stores else "<i>Нет подключенных точек</i>"

    role_str = "👑 Администратор" if user.get("role") == "admin" else "👤 Оператор"

    text = t(
        "cab_profile_card",
        full_name=user.get("full_name", "Сотрудник"),
        username=(
            f"@{user.get('username')}" if user.get("username") else "Без юзернейма"
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
    """Prompts operator for personal iikoOffice login."""
    await state.set_state(UserCabinetState.waiting_iiko_login)
    await callback.message.edit_text(
        t("cab_prompt_login"),
        reply_markup=get_cancel_input_kb(),
        parse_mode="HTML",
    )


@router.message(UserCabinetState.waiting_iiko_login)
async def process_login_input(message: types.Message, state: FSMContext):
    """Records login and prompts operator for password with self-deletion notice."""
    login = message.text.strip()
    if len(login) < 2:
        await message.answer(t("cab_invalid_login"), reply_markup=get_cancel_input_kb())
        return

    await state.update_data(iiko_login=login)
    await state.set_state(UserCabinetState.waiting_iiko_password)
    await message.answer(
        t("cab_prompt_password"),
        reply_markup=get_cancel_input_kb(),
        parse_mode="HTML",
    )


@router.message(UserCabinetState.waiting_iiko_password)
async def process_password_input(message: types.Message, state: FSMContext):
    """Validates credentials against iiko, encrypts password, and purges chat message."""
    password = message.text.strip()

    # Immediate chat hygiene: destroy message containing plaintext password
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message with password: {e}")

    data = await state.get_data()
    login = data.get("iiko_login")
    await state.clear()

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
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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


@router.callback_query(F.data == "cab:my_mappings")
async def process_view_my_mappings(callback: types.CallbackQuery):
    """Displays operator's recent item alignments for self-service revocation."""
    from storage import get_user_recent_mappings
    from keyboards.menu_kb import get_user_mappings_kb

    mappings = await get_user_recent_mappings(callback.from_user.id, limit=10)
    if not mappings:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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

    await callback.message.edit_text(
        t("cab_my_mappings_title"),
        reply_markup=get_user_mappings_kb(mappings),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("cab:revoke:"))
async def process_revoke_my_mapping(callback: types.CallbackQuery):
    """Revokes single mapping created by operator without breaking shared dictionary."""
    from storage import revoke_user_mapping

    audit_id = int(callback.data.split(":")[2])
    success = await revoke_user_mapping(callback.from_user.id, audit_id)

    if success:
        logger.info(
            f"Operator {callback.from_user.id} revoked mapping audit log #{audit_id}"
        )
        await callback.answer(t("cab_mapping_revoked_success"), show_alert=True)
    else:
        await callback.answer(t("cab_mapping_revoke_failed"), show_alert=True)

    await process_view_my_mappings(callback)


@router.callback_query(F.data == "cab:clear_creds")
async def process_clear_credentials(callback: types.CallbackQuery, state: FSMContext):
    """Unbinds personal iiko credentials from operator profile."""
    await update_user_iiko_credentials(callback.from_user.id, None, None)
    logger.info(f"User {callback.from_user.id} cleared iiko credentials.")
    await callback.answer(t("cab_creds_cleared"), show_alert=True)
    await process_open_cabinet(callback, state)


@router.callback_query(F.data == "cab:my_stores")
async def process_view_my_stores(callback: types.CallbackQuery):
    """Displays interactive toggle list of iikoChain restaurants for operator."""
    user = await get_bot_user(callback.from_user.id)
    if not user or not user.get("iiko_login") or not user.get("iiko_password_encrypted"):
        from keyboards.invoices_kb import get_setup_creds_kb
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

    # Fetch stores from iiko API under operator credentials
    stores = await asyncio.to_thread(client.get_iiko_departments_for_user, login, password)
    if not stores:
        await callback.answer("В iikoChain не найдено складов или нет прав доступа.", show_alert=True)
        return

    from storage import get_user_stores
    from keyboards.menu_kb import get_user_stores_toggle_kb

    user_stores = await get_user_stores(callback.from_user.id)
    connected_ids = {s["store_id"] for s in user_stores}

    await callback.message.edit_text(
        t("cab_my_stores_title"),
        reply_markup=get_user_stores_toggle_kb(stores, connected_ids),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("cab:toggle_store:"))
async def process_toggle_store(callback: types.CallbackQuery):
    """Toggles restaurant connection state for operator."""
    store_id = callback.data.split(":")[2]
    user = await get_bot_user(callback.from_user.id)
    if not user or not user.get("iiko_login") or not user.get("iiko_password_encrypted"):
        return

    login = user["iiko_login"]
    password = decrypt_secret(user["iiko_password_encrypted"])
    stores = await asyncio.to_thread(client.get_iiko_departments_for_user, login, password)
    target_store = next((s for s in stores if s["id"] == store_id), None)
    target_name = target_store["name"] if target_store else "Склад iiko"

    from storage import toggle_user_store
    is_connected = await toggle_user_store(callback.from_user.id, store_id, target_name)

    msg = f"✅ Точка «{target_name}» подключена!" if is_connected else f"Точка «{target_name}» отключена."
    await callback.answer(msg)
    await process_view_my_stores(callback)


@router.callback_query(F.data == "cab:cancel_input")
async def process_cancel_input(callback: types.CallbackQuery, state: FSMContext):
    """Aborts credential input and returns to cabinet."""
    await state.clear()
    await process_open_cabinet(callback, state)
