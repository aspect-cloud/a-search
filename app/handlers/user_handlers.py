import html
import logging
import os
import tempfile
import asyncio
from typing import Optional, List, Tuple, Union

from aiogram import F, Router, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from google import genai
from sqlalchemy.orm import Session
from aiohttp import ClientSession

from app.core.config import settings
from app.db.crud import get_or_create_user, add_message_to_history, clear_user_history
from app.db.models import User
from app.keyboards.reply import main_reply_keyboard
from app.schemas.gemini_schemas import GeminiResponse
from app.services.api_key_manager import get_api_key_manager
from app.services.duckduckgo import get_instant_answer, format_duckduckgo_html
from app.services.gemini_service import (
    delete_file_from_gemini,
    generate_response,
    upload_file_to_gemini,
)
from app.states.user_states import UserState
from app.utils.action_logger import log_user_action

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("start"))
@log_user_action
async def start(message: Message, state: FSMContext, db_session: Session):
    await get_or_create_user(db_session, message.from_user.id)
    user_name = html.escape(message.from_user.full_name)
    await state.clear()
    await state.set_state(UserState.MODE_SELECTION)
    await message.answer(
        settings.texts.start_message.format(user_name=user_name),
        reply_markup=main_reply_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("help"))
@log_user_action
async def help_command(message: Message):
    await message.answer(settings.texts.help_message, parse_mode="HTML")


@router.message(Command("reset"))
@log_user_action
async def reset_command(message: Message, state: FSMContext, db_session: Session):
    """Resets the conversation history for the user, handling file deletions and DB operations asynchronously."""
    user_id = message.from_user.id
    logger.info(f"Initiating reset for user {user_id}")

    # --- File Deletion (Async) ---
    user_data = await state.get_data()
    file_names = user_data.get("file_names", [])
    if file_names:
        logger.info(f"User {user_id} has files to delete: {file_names}")
        api_key_manager = get_api_key_manager()
        try:
            with api_key_manager.get_key_for_session() as api_key:
                delete_tasks = [delete_file_from_gemini(name, api_key=api_key) for name in file_names]
                results = await asyncio.gather(*delete_tasks, return_exceptions=True)
                for name, result in zip(file_names, results):
                    if isinstance(result, Exception):
                        logger.error(f"Failed to delete file {name} during reset: {result}")
        except Exception as e:
            logger.error(f"Could not acquire API key for reset file deletion: {e}")

    # --- Database History Clearing (Non-blocking) ---
    try:
        await clear_user_history(db_session, user_id)
        logger.info(f"Successfully cleared database history for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to clear database history for user {user_id}: {e}", exc_info=True)
        await message.answer(settings.texts.error_message)
        return

    # --- Finalize State and Notify User ---
    await state.clear()
    await state.set_state(UserState.MODE_SELECTION)
    await state.update_data(mode=None) # Clear the mode
    await message.answer(
        settings.texts.history_cleared,
        reply_markup=main_reply_keyboard(),
    )
    logger.info(f"Reset complete for user {user_id}")


@router.message(F.text == settings.buttons.help)
@log_user_action
async def help_button_handler(message: Message):
    """Handles the 'Help' button press."""
    await help_command(message)


@router.message(F.text == settings.buttons.clear_history)
@log_user_action
async def reset_button_handler(message: Message, state: FSMContext, db_session: Session):
    """Handles the 'Clear History' button press."""
    await reset_command(message, state, db_session)


@router.message(F.text.in_(settings.available_modes))
@log_user_action
async def set_mode(message: Message, state: FSMContext):
    mode_map = {
        settings.buttons.fast: "fast",
        settings.buttons.reasoning: "reasoning",
        settings.buttons.agent: "agent",
    }
    mode = mode_map.get(message.text)

    if not mode:
        await message.answer("Неизвестный режим.")
        return

    await state.update_data(mode=mode)
    await state.set_state(UserState.CHATTING)
    await message.answer(
        settings.texts.mode_selection.format(mode=message.text),
        reply_markup=main_reply_keyboard(),
        parse_mode="HTML",
    )


@router.message(UserState.MODE_SELECTION, F.text)
@log_user_action
async def prompt_to_select_mode(message: Message):
    """
    Catches any text message sent when the user is supposed to be selecting a mode,
    but the text is not a valid mode. Prompts them to use the keyboard.
    """
    await message.answer(
        settings.texts.select_mode_first,
        reply_markup=main_reply_keyboard()
    )


@router.message(F.photo)
@log_user_action
async def handle_album(message: Message, state: FSMContext, db_session: Session, bot: Bot, album: list[Message]):
    user_id = message.from_user.id
    status_message = await message.answer(settings.texts.media_processing, parse_mode='HTML')

    downloaded_files = []
    api_key_manager = get_api_key_manager()
    try:
        with api_key_manager.get_key_for_session() as api_key:
            current_state = await state.get_state()
            user_data = await state.get_data()
            mode = user_data.get("mode")

            # If the user is not in the CHATTING state or mode is not set, set a default mode.
            if current_state != UserState.CHATTING or not mode:
                logger.info(f"User {user_id} sent photo without selecting a mode. Setting mode to 'fast'.")
                await state.update_data(mode="fast")
                await state.set_state(UserState.CHATTING)
                mode = "fast" # Update local mode variable

            old_file_names = user_data.get("file_names", [])
            if old_file_names:
                logger.info(f"User {user_id} sent new photo(s), deleting old ones: {old_file_names}")
                for name in old_file_names:
                    try:
                        await delete_file_from_gemini(name, api_key=api_key)
                    except Exception as e:
                        logger.error(f"Failed to delete old file {name} for user {user_id}: {e}")

            captions, file_names = [], []
            for msg in album:
                if msg.caption:
                    captions.append(msg.caption)
                if msg.photo:
                    photo = msg.photo[-1]
                    file_info = await bot.get_file(photo.file_id)
                    temp_dir = tempfile.gettempdir()
                    temp_file_path = os.path.join(temp_dir, f"{photo.file_unique_id}.jpeg")
                    await bot.download_file(file_info.file_path, destination=temp_file_path)
                    downloaded_files.append(temp_file_path)

            await status_message.edit_text(settings.texts.uploading_to_google, parse_mode="HTML")
            uploaded_files_parts = []
            for file_path in downloaded_files:
                uploaded_file = await upload_file_to_gemini(file_path, api_key=api_key)
                if uploaded_file:
                    uploaded_files_parts.append(uploaded_file)

            if not uploaded_files_parts:
                await status_message.edit_text(settings.texts.media_error)
                return

            await state.update_data(uploaded_files_parts=uploaded_files_parts)
            user_content = " ".join(captions) if captions else settings.texts.photo_no_caption
            proxy_message = message.copy(update={'text': user_content, 'photo': None, 'caption': None, 'uploaded_files_parts': uploaded_files_parts})

            await handle_user_request(
                message=proxy_message, state=state, db_session=db_session, bot=bot,
                status_message=status_message, api_key=api_key,
                uploaded_files_parts=uploaded_files_parts
            )

    except Exception as e:
        logger.error(f"Error handling album for user {user_id}: {e}", exc_info=True)
        await status_message.edit_text(settings.texts.error_message)

    finally:
        for file_path in downloaded_files:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError as e:
                    logger.error(f"Error deleting temp file {file_path}: {e}", exc_info=True)


async def _run_experts_and_synthesizer(
    db_session: Session, user: User, mode: str, prompt: Union[str, List[Union[str, genai.types.Part]]], update_callback: callable, session: ClientSession, api_key: str,
    uploaded_files_parts: Optional[List[genai.types.Part]] = None,
) -> Tuple[Optional[GeminiResponse], Optional[str]]:
    expert_opinions = []
    ddg_queries = []
    expert_prompts = settings.prompts.get_experts_by_mode(mode)

    async def get_expert_opinion(expert_details, expert_num):
        expert_name = expert_details["name"]
        await update_callback(settings.statuses.get_by_mode(mode, 'experts', expert_num))
        expert_prompt = expert_details["prompt"]
        is_rag_expert = expert_details["rag"]

        expert_prompt_parts: List[Union[str, genai.types.Part]] = prompt if isinstance(prompt, list) else [genai.types.Part(text=prompt)]

        response = await generate_response(
            db_session=db_session, user=user, mode=mode, prompt=expert_prompt_parts, has_files=uploaded_files_parts is not None, is_rag_expert=is_rag_expert,
            system_instruction=expert_prompt
        )

        opinion = None
        if response and response.function_call:
            if is_rag_expert:
                call = response.function_call
                if call.name == "search_duckduckgo":
                    query = call.args.get("query", "")
                    ddg_queries.append(query)
                    await update_callback(settings.statuses.rag_expert_search)
                    
                    search_results = await get_instant_answer(query, session)

                    if isinstance(prompt, list):
                        updated_prompt = prompt + [genai.types.Part(text=f"Search results for '{query}':\n{search_results}")]
                    else:
                        updated_prompt = f"{prompt}\nSearch results for '{query}':\n{search_results}"

                    final_expert_response = await generate_response(
                        db_session=db_session,
                        user=user,
                        mode=mode,
                        prompt=updated_prompt,
                        has_files=uploaded_files_parts is not None,
                        is_rag_expert=is_rag_expert
                    )
                    opinion = final_expert_response.text
        else:
            opinion = response.text if response else None

        if opinion:
            return f"### {expert_name}'s Opinion:\n{opinion}"
        return None

    await update_callback(settings.statuses.get_by_mode(mode, 'experts_start'))
    tasks = [get_expert_opinion(expert_details, i + 1) for i, expert_details in enumerate(expert_prompts)]
    results = await asyncio.gather(*tasks)
    expert_opinions = [opinion for opinion in results if opinion is not None]

    if not expert_opinions:
        return None, None

    # Update status before synthesizing
    await update_callback(settings.statuses.get_by_mode(mode, 'synthesizer'))
    if mode == 'reasoning':
        synthesizer_prompt = settings.prompts.synthesizer_reasoning
    elif mode == 'agent':
        synthesizer_prompt = settings.prompts.synthesizer_agent
    else:
        synthesizer_prompt = settings.prompts.synthesizer_reasoning # Default or error handling
    synthesis_context = "\n\n".join(expert_opinions)

    # Final synthesizer call
    synthesizer_prompt_parts: List[Union[str, genai.types.Part]] = [genai.types.Part(text=synthesis_context)]
    if uploaded_files_parts:
        synthesizer_prompt_parts.extend(uploaded_files_parts)

    final_response = await generate_response(
        db_session=db_session, user=user, mode=mode, prompt=synthesizer_prompt_parts, has_files=uploaded_files_parts is not None, is_rag_expert=False,
        system_instruction=synthesizer_prompt
    )
    ddg_query_used = ", ".join(sorted(list(set(ddg_queries)))) if ddg_queries else None
    return final_response, ddg_query_used


@router.message(UserState.CHATTING, F.text, ~F.text.startswith('/'), ~F.text.in_(settings.available_modes))
@log_user_action
async def handle_user_request(
    message: Message, state: FSMContext, db_session: Session, bot: Bot,
    status_message: Optional[Message] = None, api_key: Optional[str] = None,
    uploaded_files_parts: Optional[List[genai.types.Part]] = None,
):
    user_id = message.from_user.id
    user_content = message.text

    user_data = await state.get_data()
    mode = user_data.get("mode")

    # If the user is not in the CHATTING state or mode is not set, prompt them to select a mode.
    if await state.get_state() != UserState.CHATTING or not mode:
        if status_message:
            await status_message.delete()
        await message.answer(settings.texts.select_mode_first, reply_markup=main_reply_keyboard())
        return

    if status_message is None:
        status_message = await message.answer(settings.texts.thinking, parse_mode='HTML')

    if not api_key:
        api_key_manager = get_api_key_manager()
        try:
            with api_key_manager.get_key_for_session() as session_key:
                return await handle_user_request(
                    message, state, db_session, bot, status_message, api_key=session_key
                )
        except Exception as e:
            logger.error(f"Failed to acquire API key for user request {user_id}: {e}", exc_info=True)
            await status_message.edit_text(settings.texts.error_message)
            return

    async def update_status(new_status: str):
        try:
            await bot.edit_message_text(new_status, chat_id=status_message.chat.id, message_id=status_message.message_id, parse_mode="HTML")
            await asyncio.sleep(1.0)  # Increased delay to make status messages more visible
        except Exception:
            pass

    try:
        file_names = user_data.get("file_names")

        user_db = await get_or_create_user(db_session, user_id)

        response_obj, ddg_query_used = None, None

        prompt_parts: List[Union[str, genai.types.Part]] = [genai.types.Part(text=user_content)]
        if uploaded_files_parts:
            prompt_parts.extend(uploaded_files_parts)

        prompt = prompt_parts

        if mode == "fast":
            response_obj = await generate_response(
                db_session=db_session, user=user_db, mode=mode, prompt=prompt, has_files=uploaded_files_parts is not None, is_rag_expert=False,
                system_instruction=settings.prompts.fast
            )
        elif mode in ["reasoning", "agent"]:
            response_obj, ddg_query_used = await _run_experts_and_synthesizer(
                db_session=db_session, user=user_db, mode=mode, prompt=prompt,
                update_callback=update_status, session=bot.session, api_key=api_key,
                uploaded_files_parts=uploaded_files_parts
            )

        response_text_or_list = response_obj.text if response_obj else settings.texts.error_message
        
        # Convert to list if it's a single string for uniform processing
        if isinstance(response_text_or_list, str):
            response_parts = [response_text_or_list]
        elif isinstance(response_text_or_list, list):
            response_parts = response_text_or_list
        else:
            response_parts = [settings.texts.error_message] # Fallback for unexpected type

        # Log the full response (concatenated if multiple parts) for history
        full_response_for_history = "\n\n".join(response_parts) if response_parts else settings.texts.empty_response
        await add_message_to_history(db_session, user_id, "user", user_content)
        await add_message_to_history(db_session, user_id, "assistant", full_response_for_history)

        if not response_parts:
            await status_message.edit_text(settings.texts.empty_response)
            return

        # Send the first part by editing the status message
        await status_message.edit_text(response_parts[0], parse_mode="HTML", disable_web_page_preview=True)

        # Send subsequent parts as new messages
        for part in response_parts[1:]:
            await message.answer(part, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Error in handle_user_request for user {user_id}: {e}", exc_info=True)
        await status_message.edit_text(settings.texts.error_message)
