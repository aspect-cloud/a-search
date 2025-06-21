from typing import List
from app.db.models import History
from app.schemas.gemini_schemas import Content, Part


def format_history(chat_history: List[History]) -> List[Content]:
    """Formats the chat history from the database into the format required by the Gemini API."""
    history_contents = []
    for message in chat_history:
        # Access attributes directly, not like a dictionary
        role = message.role
        content = message.content
        # Ensure the role is either 'user' or 'model'
        if role in ["user", "model"]:
            history_contents.append(Content(role=role, parts=[Part(text=content)]))
    return history_contents
