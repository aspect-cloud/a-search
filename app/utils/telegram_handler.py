import logging
import asyncio
from aiogram import Bot
from app.core.config import settings

class TelegramHandler(logging.Handler):
    def __init__(self, bot: Bot):
        super().__init__()
        self.bot = bot

    def emit(self, record):
        log_entry = self.format(record)
        # Escape HTML for safe rendering inside <pre> tag
        log_entry_escaped = logging.escape(log_entry)

        if settings.admin_id:
            try:
                # Fire-and-forget the message sending task to avoid blocking.
                asyncio.create_task(self.bot.send_message(settings.admin_id, f"<pre>{log_entry_escaped}</pre>"))
            except Exception as e:
                # To avoid an infinite loop if logging the error itself causes an error
                print(f"Failed to send log message to Telegram: {e}")
