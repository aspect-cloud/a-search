from pydantic import BaseModel, Field
from typing import List, Optional
from google.genai.types import FunctionCall, FinishReason, Candidate


class Part(BaseModel):
    """Represents a part of a content message, typically text."""
    text: str


class Content(BaseModel):
    """Represents a content block with a role and parts."""
    role: str
    parts: List[Part]


class GeminiResponse(BaseModel):
    """
    Represents a response from the Gemini API.
    It can contain generated text, a request to call a function, or both.
    """
    text: Optional[str] = None
    function_call: Optional[FunctionCall] = None
    finish_reason: Optional[FinishReason] = None
    # The full list of candidates from the API response, not shown in repr.
    candidates: Optional[List[Candidate]] = Field(default=None, repr=False)

    class Config:
        arbitrary_types_allowed = True
