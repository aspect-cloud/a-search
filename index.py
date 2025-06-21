import asyncio
import logging
import os
import sys
from flask import Flask, request, abort
from aiogram import Bot, Dispatcher, types
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.core.config import settings
from app.db.database import init_db, SessionLocal
from app.handlers import user_handlers
from app.middlewares.db_middleware import DbSessionMiddleware
from app.services.api_key_manager import initialize_api_key_manager

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Vercel Environment Setup ---
BOT_TOKEN = settings.bot_token
# The WEBHOOK_URL is automatically set by Vercel.
WEBHOOK_URL = f"https://{os.environ.get('VERCEL_URL')}/{BOT_TOKEN}" if 'VERCEL_URL' in os.environ else ""

# --- Bot and Dispatcher Initialization ---
try:
    init_db()
    initialize_api_key_manager(settings.gemini_api_keys)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    dp.update.middleware(DbSessionMiddleware(session_pool=SessionLocal))
    dp.include_router(user_handlers.router)

    logger.info("Bot and Dispatcher initialized for webhook.")

except Exception as e:
    logger.critical(f"Failed to initialize bot components: {e}", exc_info=True)
    sys.exit(1)

# --- Flask App Initialization ---
app = Flask(__name__)

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
async def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_str = await request.get_data()
        update = types.Update.model_validate_json(json_str)
        await dp.feed_update(bot=bot, update=update)
        return ('', 204)
    abort(403)

@app.route('/')
def index():
    return 'Bot is running!', 200

async def on_startup():
    logger.info(f'Setting webhook on: {WEBHOOK_URL}')
    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown():
    logger.info('Deleting webhook...')
    await bot.delete_webhook()

async def main():
    """Function to run the bot in polling mode."""
    # --- Database and API Key Manager Initialization ---
    init_db()
    initialize_api_key_manager(settings.gemini_api_keys)

    # --- Bot and Dispatcher Initialization for Polling ---
    bot_polling = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    storage = MemoryStorage()
    dp_polling = Dispatcher(storage=storage)

    dp_polling.update.middleware(DbSessionMiddleware(session_pool=SessionLocal))
    dp_polling.include_router(user_handlers.router)

    logger.info("Bot and Dispatcher initialized for polling.")

    # --- Start Polling ---
    try:
        await dp_polling.start_polling(bot_polling)
    finally:
        await bot_polling.session.close()

if __name__ == '__main__':
    # This block runs when the script is executed directly (e.g., `python index.py`)
    # It's intended for local development and testing.
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())

elif 'VERCEL_URL' in os.environ:
    # This block runs when the application is deployed on Vercel.
    # It sets up the webhook for the Flask app.
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(on_startup())
    else:
        loop.run_until_complete(on_startup())

