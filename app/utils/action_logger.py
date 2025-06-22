import logging
from functools import wraps
from typing import Coroutine, Any, Callable

from aiogram.types import Message


file_handler = logging.FileHandler('/tmp/user_actions.log', encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))

action_logger = logging.getLogger('user_actions')
action_logger.setLevel(logging.INFO)
action_logger.addHandler(file_handler)


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
