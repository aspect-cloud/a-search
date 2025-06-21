import asyncio
from collections import defaultdict
from typing import Dict, List, Optional

from aiogram.types import Message

# A simple in-memory cache for media groups
# {media_group_id: {"messages": [Message, ...], "timer": asyncio.TimerHandle}}
media_group_cache: Dict[str, Dict[str, object]] = defaultdict(lambda: {"messages": [], "timer": None})

async def add_message_to_group(message: Message, handler_coro, delay_seconds: float = 1.5):
    """
    Adds a message to a media group and schedules a handler to be called after a delay.

    If a message with the same media_group_id is already in the cache, the timer is reset.
    """
    media_group_id = message.media_group_id
    if not media_group_id:
        # If it's a single message, handle it immediately
        await handler_coro([message])
        return

    # Cancel the previous timer if it exists for this group
    if media_group_cache[media_group_id]["timer"]:
        media_group_cache[media_group_id]["timer"].cancel()

    # Add the new message to the group
    media_group_cache[media_group_id]["messages"].append(message)

    # Schedule the handler to be called after the delay
    loop = asyncio.get_running_loop()
    timer = loop.call_later(
        delay_seconds,
        lambda: asyncio.create_task(process_media_group(media_group_id, handler_coro))
    )
    media_group_cache[media_group_id]["timer"] = timer

async def process_media_group(media_group_id: str, handler_coro):
    """
    Retrieves all messages for a media group from the cache, calls the handler, and clears the cache for that group.
    """
    if media_group_id in media_group_cache:
        messages = media_group_cache[media_group_id]["messages"]
        # Sort messages by message_id to maintain order
        sorted_messages = sorted(messages, key=lambda m: m.message_id)
        await handler_coro(sorted_messages)
        del media_group_cache[media_group_id]
