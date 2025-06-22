import asyncio
import logging
from typing import List, Optional, Union

from google import genai
from google.genai import types
from google.api_core import exceptions

from app.core.config import settings
from app.db.models import User
from app.db.utils import build_gemini_history
from app.schemas.gemini_schemas import GeminiResponse
from app.services.api_key_manager import get_api_key_manager
from app.schemas.tools import duckduckgo_search_tool, url_context_tool

logger = logging.getLogger(__name__)


async def delete_file_from_gemini(file_name: str, api_key: str) -> None:
    """Deletes a file from Gemini using its name, following the new SDK syntax."""
    client = genai.Client(api_key=api_key)
    try:
        await client.aio.files.delete(name=file_name)
        logger.info(f"Successfully deleted file: {file_name}")
    except exceptions.NotFound:
        logger.warning(f"File not found, could not delete: {file_name}")
    except Exception as e:
        logger.error(f"An error occurred while deleting file {file_name}: {e}")
        raise


async def upload_file_to_gemini(
        file_path: str, api_key: str, display_name: Optional[str] = None
) -> Optional[types.Part]:
    """Uploads a file to Gemini and returns a Part object for use in a prompt."""
    client = genai.Client(api_key=api_key)
    try:
        with open(file_path, 'rb') as f:
            uploaded_file = await client.aio.files.upload(
                file=f
            )
        logger.info(f"Uploaded file '{uploaded_file.display_name}' as: {uploaded_file.uri}")
        return types.Part.from_uri(uri=uploaded_file.uri, mime_type=uploaded_file.mime_type)
    except Exception as e:
        logger.error(f"Failed to upload file {file_path}: {e}")
        return None


async def generate_response(
        db_session: User,
        user: User,
        mode: str,
        prompt: Union[str, List[Union[str, types.Part]]],
        has_files: bool,
        is_rag_expert: bool = False,
) -> GeminiResponse:
    """Generates a response using the new google-genai SDK with async client."""
    api_key_manager = get_api_key_manager()
    try:
        api_key = api_key_manager.get_key()
    except ValueError as e:
        logger.error(f"API key acquisition failed: {e}")
        return GeminiResponse(text=settings.texts.error_message, finish_reason="ERROR")

    client = genai.Client(api_key=api_key)
    model_name = settings.gemini_model_config.get(mode, "gemini-1.5-flash-latest")
    logger.info(f"Initiating Gemini call for mode='{mode}' with model='{model_name}' using key ...{api_key[-4:]}")

    # --- Content Construction (New SDK) ---
    history = await build_gemini_history(db_session, user, has_files)
    
    current_parts = []
    if isinstance(prompt, str):
        current_parts.append(types.Part(text=prompt))
    else:  # It's a list for multi-modal input
        for item in prompt:
            if isinstance(item, str):
                current_parts.append(types.Part(text=item))
            elif isinstance(item, types.Part):
                current_parts.append(item)
    
    contents = [*history, types.Content(role="user", parts=current_parts)]

    # --- Tool and Config Construction (New SDK) ---
    tools = []
    if is_rag_expert:
        logger.info("RAG expert mode. No tools will be passed.")
    elif mode in settings.internal_search_enabled_modes:
        tools.append(types.Tool(google_search=types.GoogleSearch()))
        # tools.append(duckduckgo_search_tool)
        # tools.append(url_context_tool)

    safety_settings = [
        genai.types.SafetySetting(
            category="HARM_CATEGORY_HATE_SPEECH",
            threshold="BLOCK_ONLY_HIGH",
        ),
        genai.types.SafetySetting(
            category="HARM_CATEGORY_HARASSMENT",
            threshold="BLOCK_ONLY_HIGH",
        ),
        genai.types.SafetySetting(
            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
            threshold="BLOCK_ONLY_HIGH",
        ),
        genai.types.SafetySetting(
            category="HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold="BLOCK_ONLY_HIGH",
        ),
    ]

    config = types.GenerateContentConfig(
        safety_settings=safety_settings,
        tools=tools,
        system_instruction=settings.prompts.get_synthesizer_by_mode(mode),
        **settings.generation_config,
    )

    try:
        response = await client.aio.models.generate_content(
            model=model_name, contents=contents, config=config
        )

        api_key_manager.release_key(api_key)

        # --- Response Processing (New SDK) ---
        if not response.candidates:
            logger.warning(f"No candidates returned from Gemini for user {user.id}")
            return GeminiResponse(text=settings.texts.empty_response, finish_reason="EMPTY")

        if response.prompt_feedback and response.prompt_feedback.block_reason:
            logger.warning(
                f"Response for user {user.id} blocked. Reason: {response.prompt_feedback.block_reason.name}"
            )
            return GeminiResponse(text=settings.texts.blocked_response, finish_reason="SAFETY")

        finish_reason = response.candidates[0].finish_reason.name
        
        text_parts = [part.text for part in response.candidates[0].content.parts if hasattr(part, 'text') and part.text]
        response_text = ''.join(text_parts)

        return GeminiResponse(text=response_text, finish_reason=finish_reason)

    except exceptions.PermissionDenied as e:
        logger.error(f"Permission denied for API key ...{api_key[-4:]}: {e}")
        api_key_manager.disable_key(api_key)
        return await generate_response(user, mode, prompt, has_files, is_rag_expert)  # Retry
    except Exception as e:
        logger.error(f"An unexpected error occurred during Gemini call: {e}", exc_info=True)
        api_key_manager.release_key(api_key)
        return GeminiResponse(text=settings.texts.error_message, finish_reason="ERROR")
