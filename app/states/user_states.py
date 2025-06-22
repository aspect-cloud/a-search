from aiogram.fsm.state import State, StatesGroup


class UserState(StatesGroup):
    MODE_SELECTION = State()
    CHATTING = State()
