import asyncio
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message


class AlbumMiddleware(BaseMiddleware):
    """This middleware is for collecting updates from media groups."""

    album_data: dict = {}

    def __init__(self, latency: int | float = 0.1):
        self.latency = latency

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not event.media_group_id:
            return await handler(event, data)

        try:
            self.album_data[event.media_group_id].append(event)
        except KeyError:
            self.album_data[event.media_group_id] = [event]
            await asyncio.sleep(self.latency)

            data["_is_last"] = True
            data["album"] = self.album_data[event.media_group_id]
            await handler(event, data)

        if data.get("_is_last"):
            del self.album_data[event.media_group_id]
