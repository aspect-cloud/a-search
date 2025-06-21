import asyncio
import logging
import os
import re
import tempfile
from typing import Optional, Tuple

from aiogram import F, Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from google.genai import types
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import crud
from app.keyboards.reply import main_reply_keyboard
from app.schemas.gemini_schemas import GeminiResponse
from app.services.duckduckgo import format_duckduckgo_html, get_instant_answer
from app.services.gemini_service import (delete_file_from_gemini, generate_response, upload_file_to_gemini)
from app.states.user_states import UserState
from app.utils.action_logger import log_user_action
from app.utils.text_utils import clean_html_for_telegram, strip_html_tags, strip_markdown_code_blocks
from app.utils.media_group_cache import add_message_to_group

logger = logging.getLogger(__name__)
router = Router()

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
ALLOWED_TAGS = ['b', 'i', 'code', 'pre']



async def send_large_message(bot: Bot, chat_id: int, text: str, status_message: Message):
    text = clean_html_for_telegram(text)
    if not text:
        try:
            await bot.edit_message_text(settings.texts.empty_response, chat_id=chat_id, message_id=status_message.message_id)
        except Exception:
            pass
        return

    parts = []
    while len(text) > 0:
        if len(text) > TELEGRAM_MAX_MESSAGE_LENGTH:
            split_pos = text.rfind('\n', 0, TELEGRAM_MAX_MESSAGE_LENGTH)
            if split_pos == -1:
                split_pos = TELEGRAM_MAX_MESSAGE_LENGTH
            part = text[:split_pos]
            text = text[split_pos:].lstrip()
            parts.append(part)
        else:
            parts.append(text)
            break

    if not parts:
        return

    try:
        await bot.edit_message_text(
            text=parts[0], chat_id=chat_id, message_id=status_message.message_id, parse_mode='HTML'
        )
    except Exception as e:
        if 'Unsupported start tag' in str(e) or "can't parse entities" in str(e):
            logger.warning(f"HTML parsing failed. Sending as plain text. Error: {e}")
            await bot.edit_message_text(
                text=strip_html_tags(parts[0]), chat_id=chat_id, message_id=status_message.message_id, parse_mode=None
            )
        else:
            logger.error(f"Error editing message: {e}", exc_info=True)
            await bot.send_message(chat_id=chat_id, text=strip_html_tags(parts[0]), parse_mode=None)

    for part in parts[1:]:
        try:
            await bot.send_message(chat_id=chat_id, text=part, parse_mode='HTML')
        except Exception as e:
            if 'Unsupported start tag' in str(e) or "can't parse entities" in str(e):
                logger.warning(f"HTML parsing failed for part. Sending as plain text. Error: {e}")
                await bot.send_message(chat_id=chat_id, text=strip_html_tags(part), parse_mode=None)
            else:
                logger.error(f"Error sending message part: {e}", exc_info=True)

@router.message(CommandStart())
@log_user_action
async def start(message: Message, state: FSMContext, db_session: Session, bot: Bot):
    user_id = message.from_user.id
    username = message.from_user.username
    user = crud.get_or_create_user(db=db_session, user_id=user_id)
    await state.set_state(UserState.chatting)
    await state.update_data(mode=user.mode)
    user_name = message.from_user.first_name
    start_message = settings.texts.start_message.format(user_name=user_name)
    await message.answer(start_message, reply_markup=main_reply_keyboard(), parse_mode="HTML")
    logger.info(f"User {user_id} ({message.from_user.full_name}) started the bot, mode set to '{user.mode}'.")

@router.message(Command("help"))
@router.message(F.text == settings.buttons.help)
@log_user_action
async def help_command(message: Message, bot: Bot):
    logger.info(f"User {message.from_user.id} requested help.")
    user_name = message.from_user.first_name
    help_text = settings.texts.help_message
    await message.answer(help_text, parse_mode='HTML')

@router.message(F.text == settings.buttons.clear_history)
@router.message(Command("clear"))
@log_user_action
async def clear_history_command(message: Message, state: FSMContext, db_session: Session, bot: Bot):
    user_id = message.from_user.id
    user_data = await state.get_data()
    file_uri = user_data.get("file_uri")

    if file_uri:
        try:
            await delete_file_from_gemini(file_uri)
            logger.info(f"Deleted remembered file {file_uri} for user {user_id}.")
        except Exception as e:
            logger.error(f"Failed to delete remembered file {file_uri} for user {user_id}: {e}")

    crud.clear_user_history(db=db_session, user_id=user_id)
    await state.clear()
    await state.set_state(UserState.chatting)
    logger.info(f"User {user_id} cleared their context (history and photo).")
    await message.answer(settings.texts.history_cleared, parse_mode='HTML')

@router.message(F.text.in_([
    settings.buttons.fast,
    settings.buttons.reasoning,
    settings.buttons.agent
]))
@log_user_action
async def select_mode(message: Message, state: FSMContext, db_session: Session, bot: Bot):
    mode_map = {
        settings.buttons.fast: "fast",
        settings.buttons.reasoning: "reasoning",
        settings.buttons.agent: "agent"
    }
    mode = mode_map.get(message.text)
    if mode:
        user_id = message.from_user.id
        await state.update_data(mode=mode)
        await state.set_state(UserState.chatting)
        crud.update_user_mode(db=db_session, user_id=user_id, mode=mode)
        logger.info(f"User {user_id} switched to '{mode}' mode and saved to DB.")
        await message.answer(
            settings.texts.mode_selection.format(mode=mode.capitalize()),
            reply_markup=main_reply_keyboard(),
            parse_mode='HTML'
        )

async def handle_media_group(messages: list[Message], state: FSMContext, db_session: Session, bot: Bot):
    """Handles a group of media messages (an album) or a single photo."""
    if not messages:
        return

    user_id = messages[0].from_user.id
    status_message = await messages[0].answer(settings.texts.media_processing, parse_mode='HTML')
    
    downloaded_files = []
    try:
        user_data = await state.get_data()
        mode = user_data.get("mode")
        if not mode:
            await status_message.delete()
            await messages[0].answer(settings.texts.select_mode_first, reply_markup=main_reply_keyboard())
            return

        # --- 1. Clear old files from state and Gemini ---
        old_file_names = user_data.get("file_names", [])
        if old_file_names:
            logger.info(f"User {user_id} sent new photo(s), deleting old ones: {old_file_names}")
            for name in old_file_names:
                try:
                    await delete_file_from_gemini(name)
                except Exception as e:
                    logger.error(f"Failed to delete old file {name} for user {user_id}: {e}")
        
        # --- 2. Download photos and collect captions ---
        captions = []
        file_names = []
        for msg in messages:
            if msg.caption:
                captions.append(msg.caption)
            if msg.photo:
                photo = msg.photo[-1]
                file_info = await bot.get_file(photo.file_id)
                temp_dir = tempfile.gettempdir()
                temp_file_path = os.path.join(temp_dir, f"{photo.file_unique_id}.jpeg")
                await bot.download_file(file_info.file_path, destination=temp_file_path)
                downloaded_files.append(temp_file_path)
                logger.info(f"Photo from user {user_id} downloaded to {temp_file_path}")

        # --- 3. Upload all to Gemini ---
        await status_message.edit_text(settings.texts.uploading_to_google, parse_mode="HTML")
        for file_path in downloaded_files:
            uploaded_file = await upload_file_to_gemini(file_path)
            if uploaded_file:
                file_names.append(uploaded_file.name)
            else:
                logger.error(f"Failed to upload file {file_path} for user {user_id}")
        
        if not file_names:
            await status_message.edit_text(settings.texts.error_file_upload)
            return

        # --- 4. Store file_names in FSM context and prepare request ---
        await state.update_data(file_names=file_names)
        
        user_content = " ".join(captions) if captions else settings.texts.photo_no_caption
        proxy_message = messages[0].copy(update={'text': user_content, 'photo': None})

        # --- 5. Handle Request ---
        await handle_user_request(
            message=proxy_message,
            state=state,
            db_session=db_session,
            bot=bot,
            status_message=status_message
        )

    except Exception as e:
        logger.error(f"Error handling media group for user {user_id}: {e}", exc_info=True)
        await status_message.edit_text(settings.texts.error_message)

    finally:
        # --- 6. Cleanup ---
        for file_path in downloaded_files:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Temporary file {file_path} deleted.")
                except OSError as e:
                    logger.error(f"Error deleting temporary file {file_path}: {e}", exc_info=True)


@router.message(F.photo)
@log_user_action
async def handle_photo(message: Message, state: FSMContext, db_session: Session, bot: Bot):
    """Catches photos and passes them to the media group handler."""
    # This function now acts as an entry point, delegating the actual logic
    # to the media group cache and handler. This allows us to gracefully
    # handle both single photos and albums (media groups) with the same logic.
    await add_message_to_group(message, lambda msgs: handle_media_group(msgs, state, db_session, bot))


async def _run_experts_and_synthesizer(
    mode: str, user_content: str, history: list, update_callback: callable, bot: Bot, file_names: Optional[list[str]] = None
) -> Tuple[Optional[GeminiResponse], Optional[str]]:
    """
    Orchestrates the process of consulting multiple AI experts and synthesizing their opinions.
    Accepts a list of file names for multi-image support.
    """
    expert_prompts = settings.prompts.get_experts_by_mode(mode)
    synthesizer_prompt = settings.prompts.get_synthesizer_by_mode(mode)

    async def run_expert(expert_prompt: str) -> Tuple[Optional[str], Optional[str]]:
        is_rag_expert = any(keyword in expert_prompt for keyword in settings.rag_fact_check_experts)
        ddg_query_used = None
        response = await generate_response(
            mode=mode, user_content=user_content, system_prompt=expert_prompt,
            history=history, is_rag_expert=is_rag_expert, bot=bot, file_names=file_names
        )

        # RAG (DuckDuckGo search) logic for experts
        if is_rag_expert and response and response.function_call:
            tool_call = response.function_call
            if tool_call.name == 'duckduckgo_search':
                query = tool_call.args.get('query', '')
                if query:
                    ddg_query_used = query
                    await update_callback(settings.statuses.get_by_mode(mode, 'rag_expert_search'))
                    search_result = get_instant_answer(query)
                    search_result_html = format_duckduckgo_html(search_result)
                    
                    # Re-run generation with search results provided as tool output
                    new_history = list(history)
                    if user_content:
                        new_history.append({'role': 'user', 'parts': [user_content]})
                    new_history.append({'role': 'model', 'parts': [types.Part(function_call=tool_call)]})
                    new_history.append({'role': 'tool', 'parts': [types.Part(function_response=types.FunctionResponse(name='duckduckgo_search', response={'result': search_result_html}))]})

                    final_expert_response = await generate_response(
                        mode=mode, user_content=None, system_prompt=expert_prompt,
                        history=new_history, is_rag_expert=is_rag_expert, bot=bot, file_names=file_names
                    )
                    return final_expert_response.text, ddg_query_used
        return response.text if response else None, None

    # Sequentially run all experts
    expert_responses = []
    for i, prompt in enumerate(expert_prompts):
        # Correctly call get_by_mode with the 'experts' stage and expert_num
        await update_callback(settings.statuses.get_by_mode(mode, 'experts', expert_num=i + 1))
        response = await run_expert(prompt)
        expert_responses.append(response)
        await asyncio.sleep(1)  # Delay to avoid API rate limits

    expert_opinions = [op for op, q in expert_responses if op]
    ddg_queries = [q for op, q in expert_responses if q]

    if not expert_opinions:
        return GeminiResponse(text=settings.texts.no_expert_opinions, finish_reason="NO_OPINIONS"), None

    # Synthesize the results
    combined_opinions = "\n\n---\n\n".join(expert_opinions)
    synthesis_context = f"User Query: '{user_content}'\n\nExpert Opinions:\n{combined_opinions}"

    await update_callback(settings.statuses.get_by_mode(mode, 'synthesizer'))
    is_synthesizer_rag = True if mode in ['agent', 'reasoning'] else False

    final_response = await generate_response(
        mode=mode, user_content=synthesis_context, system_prompt=synthesizer_prompt,
        history=[], is_rag_expert=is_synthesizer_rag, bot=bot, file_names=file_names
    )
    ddg_query_used = ", ".join(sorted(list(set(ddg_queries)))) if ddg_queries else None
    return final_response, ddg_query_used


async def handle_user_request(
    message: Message, state: FSMContext, db_session: Session, bot: Bot,
    status_message: Optional[Message] = None
):
    """
    Main handler for processing user text and photo requests.
    It now gets file_names from the FSM state, supporting multiple images.
    """
    user_id = message.from_user.id
    user_data = await state.get_data()
    mode = user_data.get("mode")
    if not mode:
        mode = "fast"
        await state.update_data(mode=mode)
        logger.info(f"User {user_id} had no mode set, defaulting to 'fast'.")
    file_names = user_data.get("file_names") # This is now a list

    if status_message is None:
        status_message = await message.answer(settings.texts.thinking, parse_mode='HTML')

    async def update_status(new_status: str):
        try:
            await bot.edit_message_text(new_status, chat_id=status_message.chat.id, message_id=status_message.message_id, parse_mode="HTML")
        except Exception as e:
            if 'message to edit not found' not in str(e):
                logger.warning(f"Could not update status message: {e}")

    try:
        chat_history = crud.get_user_history(db=db_session, user_id=user_id)
        user_content = message.text

        if not user_content and not file_names:
            await update_status(settings.texts.empty_request)
            return

        response_obj, ddg_query_used = None, None

        if mode == "fast":
            await update_status(settings.statuses.get_by_mode(mode, 'default'))
            system_prompt = settings.prompts.fast
            response_obj = await generate_response(
                mode=mode, user_content=user_content, system_prompt=system_prompt,
                bot=bot, history=chat_history, is_rag_expert=False, file_names=file_names
            )
        elif mode in ["reasoning", "agent"]:
            response_obj, ddg_query_used = await _run_experts_and_synthesizer(
                mode=mode, user_content=user_content, history=chat_history,
                update_callback=update_status, bot=bot, file_names=file_names
            )

        final_text = response_obj.text if response_obj else None

        if final_text:
            final_text = strip_markdown_code_blocks(final_text)
            final_text = clean_html_for_telegram(final_text)

            # Save to history
            crud.add_message_to_history(db=db_session, user_id=user_id, role="user", content=user_content)
            crud.add_message_to_history(db=db_session, user_id=user_id, role="model", content=final_text)
            
            if ddg_query_used:
                final_text += f'\n\n{settings.texts.used_ddg_queries.format(queries=ddg_query_used)}'

            await send_large_message(bot, status_message.chat.id, final_text, status_message)
        elif response_obj and response_obj.finish_reason != "STOP":
            # Handle cases where generation stopped for other reasons (safety, etc.)
            error_text = settings.texts.error_message
            if response_obj.finish_reason == "SAFETY":
                error_text = settings.texts.safety_error
            await update_status(error_text)
            logger.warning(f"Response generation for user {user_id} stopped. Reason: {response_obj.finish_reason}")
        elif not final_text:
            await update_status(settings.texts.error_message)

    except Exception as e:
        logger.error(f"Error in handle_user_request for user {user_id}: {e}", exc_info=True)
        await update_status(settings.texts.error_message)

@router.message(F.video | F.document | F.voice | F.video_note | F.sticker | F.audio | F.animation)
@log_user_action
async def handle_unsupported_content(message: Message, bot: Bot):
    logger.warning(f"User {message.from_user.id} sent an unsupported content type: {message.content_type}")
    await message.answer(settings.texts.unsupported_content_type)

@router.message(F.text)
@log_user_action
async def handle_text(message: Message, state: FSMContext, db_session: Session, bot: Bot):
    if message.photo:
        return

    current_state = await state.get_state()
    if current_state != UserState.chatting.state:
        await message.answer(settings.texts.select_mode_first, reply_markup=main_reply_keyboard(), parse_mode='HTML')
        return


    await handle_user_request(message, state, db_session, bot)
