import asyncio
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message


class AlbumMiddleware(BaseMiddleware):
    album_data: dict = {}

    def __init__(self, latency: int | float = 0.5):
        self.latency = latency

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        # This middleware should only handle messages with photos.
        # For any other message type, it should be a passthrough.
        if not event.photo:
            return await handler(event, data)

        # If the message is a single photo (not in a media group).
        if not event.media_group_id:
            data["album"] = [event]
            return await handler(event, data)

        # If the message is part of a media group.
        try:
            self.album_data[event.media_group_id].append(event)
        except KeyError:
            self.album_data[event.media_group_id] = [event]
            await asyncio.sleep(self.latency)

            messages = self.album_data.pop(event.media_group_id)
            data["album"] = messages
            return await handler(event, data)

        # If the message is part of an album but not the first one,
        # stop processing it further down the chain.
        return
