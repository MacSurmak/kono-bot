from aiogram import Router, types
from aiogram.filters import CommandStart, Command
from storage import validate_and_consume_invite, get_bot_user

router = Router(name="commands_router")


@router.message(CommandStart())
async def handle_start(message: types.Message):
    """Handles /start command with optional invite token deep-link."""
    args = message.text.split(maxsplit=1)
    user = message.from_user

    # Handle deep-linking invite token: /start inv_<token>
    if len(args) > 1 and args[1].startswith("inv_"):
        token = args[1].replace("inv_", "").strip()
        success = validate_and_consume_invite(
            token=token,
            telegram_id=user.id,
            username=user.username,
            full_name=user.full_name,
        )
        from loguru import logger
        from lexicon import t

        if success:
            logger.info(
                f"Invite token successfully activated by user_id={user.id} (@{user.username}, {user.full_name})"
            )
            await message.answer(
                t("start_welcome_invite", name=user.first_name), parse_mode="HTML"
            )
            return
        else:
            logger.warning(
                f"Invalid or expired invite token attempt by user_id={user.id} (@{user.username}): token='{token}'"
            )
            await message.answer(t("start_invite_invalid"), parse_mode="HTML")
            return

    from loguru import logger
    from lexicon import t

    db_user = get_bot_user(user.id)
    if db_user and db_user["is_active"]:
        await message.answer(
            t("start_registered", name=user.first_name), parse_mode="HTML"
        )
    else:
        await message.answer(t("start_unauthorized"), parse_mode="HTML")


@router.message(Command("help"))
async def handle_help(message: types.Message):
    """Displays user assistance manual from lexicon."""
    from lexicon import t

    await message.answer(t("help_text"), parse_mode="HTML")
