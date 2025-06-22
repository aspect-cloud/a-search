import asyncio
import logging
import sys

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram").setLevel(logging.WARNING)


async def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    try:
        from app.core.config import settings
        from app.db.database import async_init_db, AsyncSessionLocal
        from app.handlers import user_handlers
        from app.middlewares.db_middleware import DbSessionMiddleware
        from app.middlewares.album_middleware import AlbumMiddleware
        from app.services.api_key_manager import initialize_api_key_manager
        from aiogram import Bot, Dispatcher
        from aiogram.client.bot import DefaultBotProperties
        from aiogram.enums import ParseMode
        from aiogram.fsm.storage.memory import MemoryStorage


        await async_init_db()
        logging.info("Database initialized.")
        initialize_api_key_manager(settings.gemini_api_keys)
        logging.info("API Key Manager initialized.")


        bot = Bot(
            token=settings.bot_token, 
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)
        logger.info("Bot and Dispatcher initialized.")


        dp.update.middleware(DbSessionMiddleware(session_pool=AsyncSessionLocal))
        dp.update.middleware(AlbumMiddleware())
        dp.include_router(user_handlers.router)
        logger.info("Middlewares and routers are registered.")


        logger.info("Starting bot polling...")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)

    except (ImportError, ValueError, AttributeError) as e:

        logging.critical(f"Application failed to start: {e}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        logging.error(f"An unexpected error occurred during runtime: {e}", exc_info=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped manually.")
