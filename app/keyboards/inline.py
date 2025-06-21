from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.config import settings


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Creates the main menu keyboard with mode selections."""
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text=settings.buttons.fast_mode, callback_data="mode_fast"),
        InlineKeyboardButton(text=settings.buttons.reasoning_mode, callback_data="mode_reasoning"),
    )
    keyboard.row(
        InlineKeyboardButton(text=settings.buttons.agent_mode, callback_data="mode_agent")
    )
    return keyboard.as_markup()


def mode_menu_keyboard() -> InlineKeyboardMarkup:
    """Creates the keyboard for when a user is in a specific mode."""
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text=settings.buttons.clear_history, callback_data="clear_history")
    )
    keyboard.row(
        InlineKeyboardButton(text=settings.buttons.back_to_main, callback_data="main_menu")
    )
    return keyboard.as_markup()
