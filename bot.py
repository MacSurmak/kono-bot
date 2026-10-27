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


import os
import shutil

TMP_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "in", "telegram_tmp"
)


async def run_garbage_collector():
    """Periodically purges stale database sessions and orphaned temporary files."""
    from storage import cleanup_stale_sessions

    while True:
        try:
            await asyncio.sleep(900)  # Every 15 minutes
            stale_doc_ids = await asyncio.to_thread(cleanup_stale_sessions, 3600)
            if stale_doc_ids:
                cleaned_files = 0
                if os.path.exists(TMP_DIR):
                    for fname in os.listdir(TMP_DIR):
                        if any(fname.startswith(f"{doc_id}_") for doc_id in stale_doc_ids):
                            try:
                                os.remove(os.path.join(TMP_DIR, fname))
                                cleaned_files += 1
                            except OSError:
                                pass
                logger.info(
                    f"[GC] Purged {len(stale_doc_ids)} stale session(s) and {cleaned_files} temporary file(s)."
                )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[GC] Error in garbage collector: {e}")


async def main():
    """Initializes and runs the supply Telegram bot in polling mode."""
    setup_logger("INFO")
    logger.info("Initializing database schema and persistent storage...")
    init_db()

    # Sanitize temporary directory on startup
    if os.path.exists(TMP_DIR):
        for f in os.listdir(TMP_DIR):
            f_path = os.path.join(TMP_DIR, f)
            try:
                if os.path.isfile(f_path):
                    os.remove(f_path)
            except OSError:
                pass
    os.makedirs(TMP_DIR, exist_ok=True)
    logger.info("Temporary workspace sanitized successfully.")

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

    gc_task = asyncio.create_task(run_garbage_collector())
    try:
        await dp.start_polling(bot)
    finally:
        gc_task.cancel()
        await bot.session.close()
        logger.info("Bot session closed successfully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped manually.")
