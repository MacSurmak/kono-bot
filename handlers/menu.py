import asyncio
from aiogram import Router, types, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from loguru import logger

from lexicon import t
from iiko_client import client
from services.crypto import encrypt_secret, decrypt_secret
from config import get_admin_ids
from storage import (
    get_bot_user,
    update_user_iiko_credentials,
    update_user_default_store,
    get_all_managed_stores,
)
from keyboards.menu_kb import (
    get_main_menu_kb,
    get_cabinet_kb,
    get_default_store_selection_kb,
    get_cancel_input_kb,
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
    await callback.message.edit_text(
        t("help_text"), reply_markup=kb, parse_mode="HTML"
    )


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

    stores = await get_all_managed_stores()
    store_map = {s["store_id"]: s["name"] for s in stores}
    def_store_id = user.get("default_store_id")
    store_name = store_map.get(def_store_id, "Не выбран (выбор при каждой накладной)") if def_store_id else "Не выбран"

    role_str = "👑 Администратор" if user.get("role") == "admin" else "👤 Оператор"

    text = t(
        "cab_profile_card",
        full_name=user.get("full_name", "Сотрудник"),
        username=f"@{user.get('username')}" if user.get("username") else "Без юзернейма",
        role=role_str,
        creds_status=creds_status,
        default_store=store_name,
    )
    await callback.message.edit_text(
        text, reply_markup=get_cabinet_kb(has_creds=has_creds), parse_mode="HTML"
    )


@router.callback_query(F.data == "cab:set_creds")
async def process_start_credential_input(callback: types.CallbackQuery, state: FSMContext):
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
    if not user or not user.get("iiko_login") or not user.get("iiko_password_encrypted"):
        await callback.answer(t("cab_no_creds_alert"), show_alert=True)
        return

    login = user["iiko_login"]
    try:
        password = decrypt_secret(user["iiko_password_encrypted"])
        await asyncio.to_thread(client.test_user_credentials, login, password)
        await callback.answer(t("cab_test_ok_alert"), show_alert=True)
    except Exception as e:
        await callback.answer(t("cab_test_fail_alert", error=str(e)[:100]), show_alert=True)


@router.callback_query(F.data == "cab:clear_creds")
async def process_clear_credentials(callback: types.CallbackQuery):
    """Unbinds personal iiko credentials from operator profile."""
    await update_user_iiko_credentials(callback.from_user.id, None, None)
    logger.info(f"User {callback.from_user.id} cleared iiko credentials.")
    await callback.answer(t("cab_creds_cleared"), show_alert=True)
    await process_open_cabinet(callback, FSMContext)


@router.callback_query(F.data == "cab:choose_store")
async def process_choose_default_store(callback: types.CallbackQuery):
    """Presents list of restaurant stores to pick primary workstation."""
    user = await get_bot_user(callback.from_user.id)
    stores = await get_all_managed_stores()
    current_store_id = user.get("default_store_id") if user else None

    await callback.message.edit_text(
        t("cab_choose_store_title"),
        reply_markup=get_default_store_selection_kb(stores, current_store_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("cab:store:"))
async def process_save_default_store(callback: types.CallbackQuery):
    """Persists chosen default restaurant store to user profile."""
    store_id = callback.data.split(":")[2]
    new_store_id = None if store_id == "none" else store_id

    await update_user_default_store(callback.from_user.id, new_store_id)
    await callback.answer(t("cab_store_saved"), show_alert=True)
    await process_open_cabinet(callback, FSMContext)


@router.callback_query(F.data == "cab:cancel_input")
async def process_cancel_input(callback: types.CallbackQuery, state: FSMContext):
    """Aborts credential input and returns to cabinet."""
    await state.clear()
    await process_open_cabinet(callback, state)
