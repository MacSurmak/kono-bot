from aiogram import Router, types
from aiogram.filters import CommandStart, Command, CommandObject
from loguru import logger
from storage import validate_and_consume_invite, get_bot_user, is_admin_user
from lexicon import t
from keyboards.menu_kb import get_main_menu_kb

router = Router(name="commands_router")


@router.message(CommandStart())
async def handle_start(message: types.Message, command: CommandObject):
    """Handles /start command with optional invite token deep-link."""
    user = message.from_user
    if not user:
        return

    is_admin = await is_admin_user(user.id)

    # Handle deep-linking invite token: /start inv_<token>
    if command.args and command.args.startswith("inv_"):
        token = command.args.replace("inv_", "").strip()
        success = await validate_and_consume_invite(
            token=token,
            telegram_id=user.id,
            username=user.username,
            full_name=user.full_name,
        )

        if success:
            logger.info(
                f"Invite token successfully activated by user_id={user.id} (@{user.username}, {user.full_name})"
            )
            await message.answer(
                t("start_welcome_invite", name=user.first_name),
                reply_markup=get_main_menu_kb(is_admin=is_admin),
                parse_mode="HTML",
            )
            return
        else:
            logger.warning(
                f"Invalid or expired invite token attempt by user_id={user.id} (@{user.username}): token='{token}'"
            )
            await message.answer(t("start_invite_invalid"), parse_mode="HTML")
            return

    db_user = await get_bot_user(user.id)
    if db_user and db_user["is_active"]:
        await message.answer(
            t("start_registered", name=user.first_name),
            reply_markup=get_main_menu_kb(is_admin=is_admin),
            parse_mode="HTML",
        )
    else:
        await message.answer(t("start_unauthorized"), parse_mode="HTML")


@router.message(Command("menu", "panel"))
async def handle_menu_command(message: types.Message):
    """Displays main interactive menu via command."""
    user = message.from_user
    is_admin = await is_admin_user(user.id) if user else False
    await message.answer(
        t("menu_main_title"),
        reply_markup=get_main_menu_kb(is_admin=is_admin),
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def handle_help(message: types.Message):
    """Displays user assistance manual from lexicon."""
    await message.answer(t("help_text"), parse_mode="HTML")
