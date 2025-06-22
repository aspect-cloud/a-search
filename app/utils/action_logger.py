import logging
from functools import wraps
from typing import Coroutine, Any, Callable
from aiogram import Bot
from aiogram.types import Message
from app.utils.telegram_handler import TelegramHandler

action_logger = logging.getLogger('action_logger')

def setup_telegram_logging(bot: Bot):
    """Configures the logger to send records to Telegram."""
    # Set the level for the logger. All handlers will inherit this unless overridden.
    action_logger.setLevel(logging.INFO)

    # Create the custom Telegram handler
    telegram_handler = TelegramHandler(bot)
    telegram_handler.setLevel(logging.INFO)

    # Create a formatter
    formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    telegram_handler.setFormatter(formatter)

    # Clear existing handlers to avoid duplicates on re-deployments
    if action_logger.hasHandlers():
        action_logger.handlers.clear()

    # Add the new handler
    action_logger.addHandler(telegram_handler)
    action_logger.info("Telegram logging initialized.")


def log_user_action(func: Callable[..., Coroutine[Any, Any, Any]]) -> Callable[..., Coroutine[Any, Any, Any]]:
    @wraps(func)
    async def wrapper(message: Message, *args, **kwargs):
        if isinstance(message, Message):
            user = message.from_user
            if user:
                action_name = func.__name__
                user_id = user.id
                user_name = user.username or user.full_name


                log_message = f"{user_id} - {user_name} - {action_name}"
                action_logger.info(log_message)

        return await func(message, *args, **kwargs)
    return wrapper
