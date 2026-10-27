from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from config import cfg, get_admin_ids
from storage import get_bot_user, upsert_bot_user

get_configured_admin_ids = get_admin_ids


class AuthMiddleware(BaseMiddleware):
    """Enforces strict invitation and admin whitelisting across all events."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user or user.is_bot:
            return None

        # Automatically bootstrap SuperAdmins from configuration
        admin_ids = get_configured_admin_ids()
        if user.id in admin_ids:
            await upsert_bot_user(
                telegram_id=user.id,
                username=user.username,
                full_name=user.full_name,
                role="admin",
            )
            data["user_role"] = "admin"
            return await handler(event, data)

        # Allow /start with invite payload to reach handler for activation
        if isinstance(event, Message) and event.text and event.text.startswith("/start inv_"):
            return await handler(event, data)

        # Check existing user authorization
        db_user = await get_bot_user(user.id)
        if db_user and db_user["is_active"]:
            data["user_role"] = db_user["role"]
            return await handler(event, data)

        # Reject unauthorized access loudly and record audit log
        from loguru import logger
        from lexicon import t

        logger.warning(
            f"Unauthorized access blocked: user_id={user.id}, username=@{user.username}, full_name='{user.full_name}'"
        )

        if isinstance(event, Message):
            await event.answer(t("auth_access_denied_msg"), parse_mode="HTML")
        elif isinstance(event, CallbackQuery):
            await event.answer(t("auth_access_denied_alert"), show_alert=True)

        return None
