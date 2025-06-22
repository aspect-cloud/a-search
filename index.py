import logging
import os
import sys
from flask import Flask, request, abort
from aiogram import Bot, Dispatcher, types
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.core.config import settings
from app.db.database import async_init_db, AsyncSessionLocal as SessionLocal
from app.handlers import user_handlers
from app.middlewares.db_middleware import DbSessionMiddleware
from app.middlewares.session_middleware import AiogramSessionMiddleware
from app.middlewares.album_middleware import AlbumMiddleware
from app.services.api_key_manager import initialize_api_key_manager


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = settings.bot_token

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)

dp.update.outer_middleware(AiogramSessionMiddleware())
dp.update.middleware(DbSessionMiddleware(session_pool=SessionLocal))
user_handlers.router.message.middleware(AlbumMiddleware())
dp.include_router(user_handlers.router)

app = Flask(__name__)

async def on_startup():
    await async_init_db()
    initialize_api_key_manager(settings.gemini_api_keys)
    webhook_url = f'{settings.webhook_url.rstrip("/")}/{BOT_TOKEN}'
    await bot.set_webhook(webhook_url)
    logger.info(f"Webhook set to {webhook_url}")

# Run startup tasks
import asyncio

# This is a bit of a hack for Vercel's environment.
# We run the async startup function in a blocking way.
try:
    asyncio.get_event_loop().run_until_complete(on_startup())
except Exception as e:
    logger.critical(f"Failed to complete startup: {e}", exc_info=True)
    # We don't exit here, as it might be a temporary issue
    # and we want the Flask app to be available for Vercel's health checks.

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
async def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_str = request.get_data()
        update = types.Update.model_validate_json(json_str)
        await dp.feed_update(bot=bot, update=update)
        return ('', 204)
    abort(403)

@app.route('/')
def index():
    return 'Bot is running!', 200


