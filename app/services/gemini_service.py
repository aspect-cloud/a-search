import logging

from typing import List, Optional, Dict, Any, Union
import time

from google import genai
from google.genai import types
from google.api_core import exceptions as google_exceptions
from PIL.Image import Image

from app.core.config import settings
from app.schemas.tools import duckduckgo_search_tool, url_context_tool
from app.services.api_key_manager import get_api_key_manager
from app.schemas.gemini_schemas import GeminiResponse
from app.services.duckduckgo import get_instant_answer, format_duckduckgo_html
import json
import tempfile
import os
from aiogram import Bot


logger = logging.getLogger(__name__)

async def upload_file_to_gemini(file_path: str) -> Optional[types.File]:
    api_key_manager = get_api_key_manager()
    api_key = api_key_manager.get_key()
    if not api_key:
        logger.error("Could not get a Gemini API key for file upload.")
        return None

    try:
        logger.info(f"Uploading file {file_path} to Gemini File API...")
        client = genai.Client(api_key=api_key)

        uploaded_file = client.files.upload(file=file_path)
        logger.info(f"Successfully uploaded file. URI: {uploaded_file.uri}")
        api_key_manager.release_key(api_key)
        return uploaded_file
    except Exception as e:
        logger.error(f"Failed to upload file to Gemini: {e}", exc_info=True)
        api_key_manager.report_failure(api_key, is_rate_limit=False)
        return None

async def delete_file_from_gemini(file_name: str):
    """Deletes a file from the Gemini File API using its name."""
    api_key_manager = get_api_key_manager()
    api_key = api_key_manager.get_key()
    if not api_key:
        logger.error("Could not get a Gemini API key for file deletion.")
        return

    try:
        logger.info(f"Deleting file {file_name} from Gemini File API...")
        client = genai.Client(api_key=api_key)
        # The SDK does not currently have an async delete method, so we use the sync one.
        client.files.delete(name=file_name)
        logger.info(f"Successfully deleted file {file_name}.")
        api_key_manager.release_key(api_key)
    except Exception as e:
        logger.error(f"Failed to delete file {file_name} from Gemini: {e}", exc_info=True)
        # Ensure key is released even on failure
        api_key_manager.release_key(api_key)

async def generate_response(
    mode: str,
    user_content: Union[str, List[Any]],
    system_prompt: str,
    bot: Bot,
    history: Optional[List[Dict[str, Any]]] = None,
    is_rag_expert: bool = False,
    file_names: Optional[List[str]] = None,
) -> GeminiResponse:
    api_key_manager = get_api_key_manager()
    model_name = settings.gemini_model_config.get(mode, "gemini-1.5-flash-latest")
    logger.info(f"Initiating Gemini call for mode='{mode}' with model='{model_name}'")


    tools = []
    if mode in settings.internal_search_enabled_modes and not is_rag_expert:
        tools.append(types.Tool(google_search=types.GoogleSearch()))
        tools.append(url_context_tool)
        logger.info(f"Enabling Google Search and URL Context for mode '{mode}'")
    elif is_rag_expert:

        logger.info("RAG expert mode. No tools will be passed to the Gemini API.")
        pass  # The 'tools' list remains empty for RAG experts.

    # --- 2. Content Construction ---
    final_contents = []
    if history:
        for msg in history:
            if isinstance(msg, dict):
                role = msg.get('role')
                content = msg.get('content') or msg.get('parts')
            else:
                role = 'model' if getattr(msg, 'role', None) == 'assistant' else getattr(msg, 'role', None)
                content = getattr(msg, 'content', None)

            if content is None:
                continue

            processed_parts = []
            
            # Check if content is a media JSON string
            is_media = False
            if isinstance(content, str):
                try:
                    media_info = json.loads(content)
                    if isinstance(media_info, dict) and media_info.get("type") == "media":
                        is_media = True
                        # Use the stored URI directly instead of re-downloading
                        if 'uri' in media_info:
                            logger.info(f"Using cached media URI from history: {media_info['uri']}")
                            processed_parts.append(types.Part(file_data=types.FileData(mime_type=media_info['mime_type'], file_uri=media_info['uri'])))
                            if media_info.get('caption'):
                                processed_parts.append(types.Part(text=media_info['caption']))
                        else:
                             logger.warning(f"Media in history found but no URI. file_id={media_info.get('file_id')}. This might be an old record.")

                except (json.JSONDecodeError, TypeError):
                    pass # It's just a string

            # If not media, process as before
            if not is_media:
                # Ensure content is a list to iterate over
                parts_to_process = content if isinstance(content, list) else [content]
                for p in parts_to_process:
                    if hasattr(p, '__class__') and p.__class__.__name__ == 'Part':
                        processed_parts.append(p)
                    elif isinstance(p, dict) and ('function_call' in p or 'function_response' in p):
                        # Если это function_response с результатом DuckDuckGo, вставить HTML
                        if 'function_response' in p and hasattr(p['function_response'], 'response'):
                            resp = p['function_response'].response
                            if isinstance(resp, dict) and 'result' in resp:
                                processed_parts.append(types.Part(text=resp['result']))
                            elif isinstance(resp, str):
                                processed_parts.append(types.Part(text=resp))
                            else:
                                processed_parts.append(types.Part(**p))
                        else:
                            processed_parts.append(types.Part(**p))
                    # Otherwise, treat as text
                    elif isinstance(p, str):
                        processed_parts.append(types.Part(text=p))

            if processed_parts:
                final_contents.append(types.Content(role=role, parts=processed_parts))

    # Add current user message and file(s) if they exist
    user_parts = []
    if user_content:
        user_parts.append(types.Part(text=str(user_content)))
    
    # Handle multiple file names by fetching the file objects and creating Parts
    if file_names:
        # This part must be synchronous for now as we need the client
        client_for_files = genai.Client(api_key=get_api_key_manager().get_key(peek=True))
        for name in file_names:
            try:
                # Fetch the file metadata from the Gemini File API
                file_obj = client_for_files.files.get(name=name)
                # Manually construct a Part with FileData, as the low-level API requires it.
                # This ensures the 'data' field in the request is correctly populated.
                part = types.Part(
                    file_data=types.FileData(
                        mime_type=file_obj.mime_type,
                        file_uri=file_obj.uri
                    )
                )
                user_parts.append(part)
            except Exception as e:
                logger.error(f"Failed to create Part for file name {name}: {e}", exc_info=True)

    if user_parts:
        final_contents.append(types.Content(role='user', parts=user_parts))

    # Генеративные фразы ожидания для разных режимов
    wait_phrases = {
        'fast': [
            '🚀 Молниеносный поиск...',
            '🔎 Ищу самые свежие данные...',
            '⚡️ Секунду, формирую ответ...'
        ],
        'reasoning': [
            '🧠 Анализирую источники...',
            '📚 Синтезирую факты...',
            '🔬 Проверяю гипотезы...'
        ],
        'agent': [
            '🤖 Совещаюсь с экспертами...',
            '🌐 Запрашиваю данные у агентов...',
            '🗂️ Объединяю мнения...' 
        ]
    }
    t0 = time.time()
    last_update = t0
    wait_idx = 0

    # --- 3. API Call with Retry Logic ---
    for i in range(len(api_key_manager.keys)):
        api_key_used = api_key_manager.get_key()
        if not api_key_used:
            logger.error("All API keys are on cooldown or failed. Could not get a Gemini API key.")
            break

        logger.info(f"Attempt {i+1}/{len(api_key_manager.keys)}: Using API Key ending in '...{api_key_used[-4:]}'")

        try:

            client = genai.Client(api_key=api_key_used)


            # Combine the base generation config with request-specific parameters.
            config_params = settings.generation_config.model_dump()
            config_params.update({
                "system_instruction": system_prompt,
                "tools": tools,
                "candidate_count": 1,
            })
            config = types.GenerateContentConfig(**config_params)


            response = await client.aio.models.generate_content(
                model=f"models/{model_name}",
                contents=final_contents,
                config=config,
            )

            logger.info(f"Successfully received response from Gemini using key '...{api_key_used[-4:]}'")
            api_key_manager.release_key(api_key_used)

            return _process_gemini_response(response)

        except google_exceptions.ResourceExhausted as e:
            logger.warning(f"API key '...{api_key_used[-4:]}' hit a rate limit (429). Placing it on cooldown.")
            api_key_manager.report_failure(api_key_used, is_rate_limit=True)

        except google_exceptions.PermissionDenied as e:
            logger.error(f"API key '...{api_key_used[-4:]}' is invalid or has been revoked (Permission Denied). Marking as failed.", exc_info=True)
            api_key_manager.report_failure(api_key_used, is_rate_limit=False)

        except Exception as e:
            logger.error(f"An unexpected error occurred with API key '...{api_key_used[-4:]}': {e}", exc_info=True)
            api_key_manager.report_failure(api_key_used, is_rate_limit=True)


    logger.error("All API keys failed to generate a response.")
    return GeminiResponse(text=settings.texts.all_keys_failed, finish_reason="ALL_KEYS_FAILED")


def _process_gemini_response(response: types.GenerateContentResponse) -> GeminiResponse:
    try:
        candidate = response.candidates[0]
        finish_reason_name = candidate.finish_reason.name

        if finish_reason_name in ["SAFETY", "RECITATION"]:
            logger.warning(f"Content generation stopped due to: {finish_reason_name}")
            return GeminiResponse(
                text=settings.texts.blocked_response,
                finish_reason=finish_reason_name,
                candidates=response.candidates
            )

        response_text = None
        function_calls = None
        if candidate.content and candidate.content.parts:

            if candidate.content.parts[0].function_call:
                function_calls = candidate.content.parts[0].function_call
            else:
                response_text = "".join(part.text for part in candidate.content.parts if hasattr(part, 'text'))

        return GeminiResponse(
            text=response_text,
            function_call=function_calls,
            finish_reason=finish_reason_name,
            candidates=response.candidates
        )

    except (IndexError, AttributeError) as e:
        logger.error(f"Error processing Gemini response: {e}. Full response: {response}", exc_info=True)
        return GeminiResponse(text=settings.texts.empty_response, finish_reason="PROCESSING_ERROR")
