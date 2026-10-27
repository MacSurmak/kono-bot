import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from lexicon import t


class ThrottlingMiddleware(BaseMiddleware):
    """Prevents double-click race conditions and message flood."""

    def __init__(self, rate_limit: float = 0.5):
        self.rate_limit = rate_limit
        self._user_last_action: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user or user.is_bot:
            return await handler(event, data)

        now = time.monotonic()
        last_time = self._user_last_action.get(user.id, 0.0)

        if now - last_time < self.rate_limit:
            if isinstance(event, CallbackQuery):
                await event.answer(t("throttling_warning"), show_alert=False)
            elif isinstance(event, Message):
                await event.answer(t("throttling_warning"))
            return None

        self._user_last_action[user.id] = now

        # Periodic garbage cleanup of stale user timestamps
        if len(self._user_last_action) > 1000:
            threshold = now - 60.0
            self._user_last_action = {
                uid: ts for uid, ts in self._user_last_action.items() if ts > threshold
            }

        return await handler(event, data)
