from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import Update


class AiogramSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        async with AiohttpSession() as session:
            data["bot"].session = session
            return await handler(event, data)
