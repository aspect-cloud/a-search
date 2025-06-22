import logging
import json
from typing import List, Optional, Dict, Any, Union

from google import genai
from google.api_core import exceptions as google_exceptions

from app.config import settings
from app.schemas.gemini_schemas import GeminiResponse
from app.schemas.tools import duckduckgo_search_tool, url_context_tool

logger = logging.getLogger(__name__)


async def upload_file_to_gemini(file_path: str, api_key: str) -> Optional[genai.types.File]:
    """Uploads a file to the Gemini File API using the new google-genai SDK."""
    logger.info(f"Uploading file {file_path} with key ...{api_key[-4:]}")
    try:
        client = genai.Client(api_key=api_key)
        # The new SDK's upload function is synchronous, but we call it from an async func
        uploaded_file = client.files.upload(file=file_path)
        logger.info(f"Successfully uploaded file. URI: {uploaded_file.uri}")
        return uploaded_file
    except Exception as e:
        logger.error(f"Failed to upload file {file_path}: {e}", exc_info=True)
        return None


async def delete_file_from_gemini(file_name: str, api_key: str):
    """Deletes a file from the Gemini File API using its name."""
    logger.info(f"Deleting file {file_name} with key ...{api_key[-4:]}")
    try:
        client = genai.Client(api_key=api_key)
        client.files.delete(name=file_name)
        logger.info(f"Successfully deleted file {file_name}.")
    except Exception as e:
        logger.error(f"Failed to delete file {file_name}: {e}", exc_info=True)


def _process_gemini_response(response: genai.types.GenerateContentResponse) -> GeminiResponse:
    """Helper to process the response from Gemini API."""
    try:
        candidate = response.candidates[0]
        finish_reason = candidate.finish_reason.name if candidate.finish_reason else "UNKNOWN"

        if finish_reason in ["SAFETY", "RECITATION"]:
            logger.warning(f"Content generation stopped due to: {finish_reason}")
            return GeminiResponse(
                text=settings.texts.blocked_response,
                finish_reason=finish_reason,
                function_calls=None,
            )

        text_parts = []
        function_calls = []
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.function_call:
                    function_calls.append(part.function_call)
                if hasattr(part, 'text') and part.text:
                    text_parts.append(part.text)

        return GeminiResponse(
            text=''.join(text_parts) if text_parts else None,
            finish_reason=finish_reason,
            function_calls=function_calls if function_calls else None,
        )
    except (IndexError, AttributeError) as e:
        logger.error(f"Error processing Gemini response: {e}. Response: {response}", exc_info=True)
        return GeminiResponse(text=settings.texts.error_message, finish_reason="ERROR")


async def generate_response(
    mode: str,
    user_content: Union[str, List[Any]],
    system_prompt: str,
    history: Optional[List[Dict[str, Any]]] = None,
    is_rag_expert: bool = False,
    file_names: Optional[List[str]] = None,
    api_key: str = None,
) -> GeminiResponse:
    """Generates a response using the new google-genai SDK with async client."""
    if not api_key:
        logger.error("Gemini API key is missing.")
        return GeminiResponse(text=settings.texts.error_message, finish_reason="ERROR")

    client = genai.Client(api_key=api_key)
    model_name = settings.gemini_model_config.get(mode, "gemini-1.5-flash-latest")
    logger.info(f"Initiating Gemini call for mode='{mode}' with model='{model_name}' using key ...{api_key[-4:]}")

    # --- Content Construction ---
    contents = []
    if history:
        contents.extend(history)

    user_parts = []
    if user_content:
        user_parts.append(user_content)

    if file_names:
        for name in file_names:
            # The new SDK requires a File object or a URI string for generation
            # We pass the name, which acts as the resource identifier like 'files/xxxx'
            user_parts.append(genai.types.Part(file_data=genai.types.FileData(file_uri=name)))

    if user_parts:
        contents.append({'role': 'user', 'parts': user_parts})

    # --- Tools and Config ---
    tools = []
    if is_rag_expert:
        logger.info("RAG expert mode. No tools will be passed to the Gemini API.")
    elif mode in settings.internal_search_enabled_modes:
        tools.append(genai.types.Tool(google_search=genai.types.GoogleSearch()))
        tools.append(duckduckgo_search_tool)
        tools.append(url_context_tool)
        logger.info(f"Enabling Google Search, DuckDuckGo, and URL Context for mode '{mode}'")

    generation_config = genai.types.GenerateContentConfig(
        temperature=settings.gemini_generation_config.get("temperature"),
        top_p=settings.gemini_generation_config.get("top_p"),
        top_k=settings.gemini_generation_config.get("top_k"),
        max_output_tokens=settings.gemini_generation_config.get("max_output_tokens"),
    )

    safety_settings = {
        category.name: threshold.name
        for category, threshold in settings.gemini_safety_settings.items()
    }

    try:
        response = await client.aio.models.generate_content(
            model=model_name,
            contents=contents,
            generation_config=generation_config,
            safety_settings=safety_settings,
            tools=tools,
            system_instruction=system_prompt,
        )
        logger.info(f"Gemini call successful with key ...{api_key[-4:]}")
        return _process_gemini_response(response)

    except google_exceptions.PermissionDenied as e:
        logger.error(f"Gemini API Permission Denied (key ...{api_key[-4:]}): {e}", exc_info=True)
        # This specific error is often due to key mismatches in a session.
        # The session manager should handle this, but we return a specific message.
        return GeminiResponse(text=settings.texts.permission_error, finish_reason="PERMISSION_DENIED")
    except Exception as e:
        logger.error(f"An unexpected error occurred during Gemini API call: {e}", exc_info=True)
        return GeminiResponse(text=settings.texts.error_message, finish_reason="ERROR")

        return GeminiResponse(
            text=response_text,
            function_call=function_calls,
            finish_reason=finish_reason_name,
            candidates=response.candidates
        )

    except (IndexError, AttributeError) as e:
        logger.error(f"Error processing Gemini response: {e}. Full response: {response}", exc_info=True)
        return GeminiResponse(text=settings.texts.empty_response, finish_reason="PROCESSING_ERROR")
