import html
from functools import wraps
from typing import Coroutine, Any, Callable
from aiogram.types import Message
from app.core.config import settings


def log_user_action(func: Callable[..., Coroutine[Any, Any, Any]]) -> Callable[..., Coroutine[Any, Any, Any]]:
    """A decorator that logs user actions by sending a message to the admin."""
    @wraps(func)
    async def wrapper(message: Message, *args, **kwargs):
        # Log the action by sending a message to the admin
        if settings.admin_id and isinstance(message, Message):
            user = message.from_user
            if user:
                action_name = func.__name__
                user_id = user.id
                user_name = user.username or user.full_name
                log_text = f"{user_id} - {user_name} - {action_name}"
                log_text_escaped = html.escape(log_text)
                try:
                    # Await the send_message call directly to ensure it completes
                    await message.bot.send_message(
                        settings.admin_id,
                        f"<pre>{log_text_escaped}</pre>"
                    )
                except Exception as e:
                    # If logging to Telegram fails, print to console to not crash the main function
                    print(f"Failed to send log to Telegram: {e}")

        # Execute the original handler function
        return await func(message, *args, **kwargs)
    return wrapper
