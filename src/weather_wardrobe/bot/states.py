from aiogram.fsm.state import State, StatesGroup


class BotStates(StatesGroup):
    """FSM states for interactive onboarding and settings input."""

    waiting_city = State()
    waiting_custom_time = State()
    waiting_active_hours = State()
    waiting_wardrobe = State()
