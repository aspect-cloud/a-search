from aiogram.fsm.state import State, StatesGroup


class UserState(StatesGroup):
    mode = State()  # To store the selected mode: 'fast', 'reasoning', 'agent'
    chatting = State() # General state for when the user is interacting with the bot
