from sqlalchemy.orm import Session, object_session
from typing import List, Dict

from . import crud
from .models import User, History


async def build_gemini_history(
    db_session: Session, user: User, has_files: bool
) -> List[Dict[str, any]]:
    """
    Builds a chat history for the Gemini API from the user's database records.

    Args:
        db_session: The database session.
        user: The user object from the database.
        has_files: Boolean indicating if files are part of the context.

    Returns:
        A list of dictionaries formatted for the Gemini API.
    """
    history_records: List[History] = await crud.get_user_history(db_session, user.id)

    gemini_history = []
    for record in history_records:
        role = "model" if record.role == "assistant" else record.role
        if role not in ["user", "model"]:
            continue
        gemini_history.append({"role": role, "parts": [record.content]})

    return gemini_history
