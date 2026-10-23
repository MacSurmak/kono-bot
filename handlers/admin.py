from aiogram import Router, types, F
from aiogram.filters import Command
from config import cfg
from keyboards.admin_kb import get_admin_main_kb
from storage import create_invite_token, get_all_bot_users

router = Router(name="admin_router")
ADMIN_ID = int(cfg["telegram"]["admin_id"])


from lexicon import t


@router.message(Command("admin"))
async def handle_admin_panel(message: types.Message):
    """Entrypoint to admin panel for privileged operators."""
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(t("admin_panel_title"), reply_markup=get_admin_main_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin:create_invite")
async def process_create_invite(callback: types.CallbackQuery):
    """Generates secure one-time invite deep-link."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    bot_info = await callback.bot.get_me()
    token = create_invite_token(created_by=callback.from_user.id)
    invite_url = f"https://t.me/{bot_info.username}?start=inv_{token}"

    await callback.message.answer(t("admin_invite_created", invite_url=invite_url), parse_mode="HTML")


@router.callback_query(F.data == "admin:list_users")
async def process_list_users(callback: types.CallbackQuery):
    """Displays active registered users."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    users = get_all_bot_users()
    if not users:
        await callback.message.answer(t("admin_users_empty"))
        return

    lines = [t("admin_users_title")]
    for idx, u in enumerate(users, 1):
        username_str = f"(@{u['username']})" if u["username"] else ""
        role_badge = "👑 [Админ]" if u["role"] == "admin" else "👤 [Оператор]"
        lines.append(f"{idx}. {role_badge} <b>{u['full_name']}</b> {username_str} — ID: <code>{u['telegram_id']}</code>")

    await callback.message.answer("\n".join(lines), parse_mode="HTML")
