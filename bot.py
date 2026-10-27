import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

from config import cfg
from storage import init_db
from middlewares.auth import AuthMiddleware
from handlers import main_router
from services.logger import setup_logger


async def main():
    """Initializes and runs the supply Telegram bot in polling mode."""
    setup_logger("INFO")
    logger.info("Initializing database schema and persistent storage...")
    init_db()

    bot_token = cfg["telegram"]["bot_token"]
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode="HTML"))

    from aiogram.utils.callback_answer import CallbackAnswerMiddleware
    from middlewares.throttling import ThrottlingMiddleware
    from lexicon import set_bot_commands

    # In-memory FSM storage is completely sufficient and self-contained for local deployment
    dp = Dispatcher(storage=MemoryStorage())

    # Register middlewares in strict sequential order
    dp.callback_query.middleware(CallbackAnswerMiddleware())
    dp.update.middleware(ThrottlingMiddleware(rate_limit=0.5))
    dp.update.middleware(AuthMiddleware())

    # Include main handlers
    dp.include_router(main_router)

    # Set persistent Telegram menu commands
    await set_bot_commands(bot)

    logger.info("Starting Telegram Bot long-polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Bot session closed successfully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped manually.")
