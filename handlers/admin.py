from aiogram import Router, types, F
from aiogram.filters import Command
from config import cfg
from keyboards.admin_kb import get_admin_main_kb
from storage import create_invite_token, get_all_bot_users

router = Router(name="admin_router")
ADMIN_ID = int(cfg["telegram"]["admin_id"])


@router.message(Command("admin"))
async def handle_admin_panel(message: types.Message):
    """Entrypoint to admin panel for privileged operators."""
    if message.from_user.id != ADMIN_ID:
        return

    text = (
        "🛠 <b>Панель управления доступом KONO Supply:</b>\n\n"
        "Здесь вы можете генерировать приглашения для сотрудников и просматривать список пользователей."
    )
    await message.answer(text, reply_markup=get_admin_main_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin:create_invite")
async def process_create_invite(callback: types.CallbackQuery):
    """Generates secure one-time invite deep-link."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Отказано в доступе.", show_alert=True)
        return

    bot_info = await callback.bot.get_me()
    token = create_invite_token(created_by=callback.from_user.id)
    invite_url = f"https://t.me/{bot_info.username}?start=inv_{token}"

    text = (
        "🎟 <b>Создана новая ссылка-приглашение:</b>\n\n"
        f"<code>{invite_url}</code>\n\n"
        "<i>Ссылка одноразовая. Отправьте её сотруднику для авторизации в боте.</i>"
    )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:list_users")
async def process_list_users(callback: types.CallbackQuery):
    """Displays active registered users."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Отказано в доступе.", show_alert=True)
        return

    users = get_all_bot_users()
    if not users:
        await callback.message.answer("Список пользователей пуст.")
        await callback.answer()
        return

    lines = ["👥 <b>Авторизованные пользователи:</b>\n"]
    for idx, u in enumerate(users, 1):
        username_str = f"(@{u['username']})" if u["username"] else ""
        role_badge = "👑 [Админ]" if u["role"] == "admin" else "👤 [Оператор]"
        lines.append(f"{idx}. {role_badge} <b>{u['full_name']}</b> {username_str} — ID: <code>{u['telegram_id']}</code>")

    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.answer()
