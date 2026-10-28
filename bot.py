# ==============================================================================
# ARCHITECTURAL INVARIANT: MODULE LOAD ORDER & TOP-LEVEL IMPORT DISCIPLINE
#
# RULE: All module dependencies MUST be explicitly declared at the top of the file
# according to PEP 8 standards. Fail-Fast on boot: if any dependency or symbol
# is missing, the application must crash loudly during container initialization.
#
# FORBIDDEN:
# - Placing `import` statements inside functions or coroutines (lazy imports).
# - Swallowing initialization errors to mask missing infrastructure.
# ==============================================================================

import os
import shutil
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
from loguru import logger

from config import cfg, SESSION_CLEANUP_TTL_SECONDS
from storage import init_db, close_db, cleanup_stale_sessions
from middlewares.auth import AuthMiddleware
from middlewares.throttling import ThrottlingMiddleware
from handlers import main_router
from lexicon import set_bot_commands
from services.logger import setup_logger

TMP_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "in", "telegram_tmp"
)


async def run_garbage_collector():
    """Periodically purges stale database sessions and orphaned temporary files."""
    while True:
        try:
            await asyncio.sleep(900)  # Every 15 minutes
            stale_doc_ids = await cleanup_stale_sessions(SESSION_CLEANUP_TTL_SECONDS)
            if stale_doc_ids:
                cleaned_files = 0
                if os.path.exists(TMP_DIR):
                    for fname in os.listdir(TMP_DIR):
                        if any(
                            fname.startswith(f"{doc_id}_") for doc_id in stale_doc_ids
                        ):
                            try:
                                os.remove(os.path.join(TMP_DIR, fname))
                                cleaned_files += 1
                            except OSError as err:
                                logger.warning(
                                    f"[GC] Failed to remove orphaned temporary file '{fname}': {err}"
                                )
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
    logger.info("Initializing PostgreSQL connection pool and persistent schema...")
    await init_db()

    # Sanitize temporary directory on startup
    if os.path.exists(TMP_DIR):
        for f in os.listdir(TMP_DIR):
            f_path = os.path.join(TMP_DIR, f)
            try:
                if os.path.isfile(f_path):
                    os.remove(f_path)
            except OSError as err:
                logger.warning(
                    f"Could not purge temporary file '{f}' during startup sanitization: {err}"
                )
    os.makedirs(TMP_DIR, exist_ok=True)
    logger.info("Temporary workspace sanitized successfully.")

    bot_token = cfg["telegram"]["bot_token"]
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode="HTML"))

    redis_url = os.getenv("REDIS_URL")
    if not redis_url or not redis_url.strip():
        raise RuntimeError(
            "CRITICAL CONFIGURATION ERROR: 'REDIS_URL' environment variable is not set."
        )

    storage = RedisStorage.from_url(redis_url.strip())
    dp = Dispatcher(storage=storage)

    # Register middlewares on concrete event buses to guarantee exact object typing
    dp.callback_query.middleware(CallbackAnswerMiddleware())

    throttler = ThrottlingMiddleware(rate_limit=0.5)
    auth_guard = AuthMiddleware()

    # Throttling is applied strictly to callback queries to prevent double-click race conditions
    dp.callback_query.middleware(throttler)

    dp.message.middleware(auth_guard)
    dp.callback_query.middleware(auth_guard)

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
        await close_db()
        logger.info("Bot session and database connections closed successfully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped manually.")
