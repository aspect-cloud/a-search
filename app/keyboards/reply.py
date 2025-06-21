from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from app.core.config import settings

def main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Creates a persistent reply keyboard for mode selection."""
    buttons = [
        [
            KeyboardButton(text=settings.buttons.fast),
            KeyboardButton(text=settings.buttons.reasoning),
            KeyboardButton(text=settings.buttons.agent)
        ],
        [
            KeyboardButton(text=settings.buttons.help),
            KeyboardButton(text=settings.buttons.clear_history)
        ]
    ]
    keyboard = ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        input_field_placeholder=settings.texts.input_placeholder
    )
    return keyboard
