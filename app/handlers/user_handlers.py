import html
import logging
import os
import tempfile
from typing import Optional, List, Tuple

from aiogram import F, Router, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from google import genai
from sqlalchemy.orm import Session
from aiohttp import ClientSession

from app.core.config import settings
from app.db.crud import get_or_create_user, add_message_to_history
from app.db.utils import build_gemini_history
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
    get_or_create_user(db_session, message.from_user.id)
    await state.clear()
    await state.set_state(UserState.MODE_SELECTION)
    await message.answer(
        settings.texts.start_message, reply_markup=main_reply_keyboard()
    )


@router.message(Command("help"))
@log_user_action
async def help_command(message: Message):
    await message.answer(settings.texts.help_message, parse_mode="HTML")


@router.message(Command("reset"))
@log_user_action
async def reset_command(message: Message, state: FSMContext, db_session: Session):
    user_id = message.from_user.id
    user_data = await state.get_data()
    file_names = user_data.get("file_names", [])

    if file_names:
        api_key_manager = get_api_key_manager()
        try:
            with api_key_manager.get_key_for_session() as api_key:
                logger.info(f"Resetting chat for user {user_id}, deleting files: {file_names}")
                for name in file_names:
                    try:
                        await delete_file_from_gemini(name, api_key=api_key)
                    except Exception as e:
                        logger.error(f"Failed to delete file {name} during reset: {e}")
        except Exception as e:
            logger.error(f"Could not acquire API key for reset file deletion: {e}")

    await state.clear()
    await state.set_state(UserState.MODE_SELECTION)

    user = get_or_create_user(db_session, user_id)
    user.history = []
    db_session.commit()

    await message.answer(settings.texts.reset_message, reply_markup=main_reply_keyboard())


@router.message(UserState.MODE_SELECTION, F.text.in_(settings.available_modes))
@log_user_action
async def set_mode(message: Message, state: FSMContext):
    mode = message.text.lower()
    await state.update_data(mode=mode)
    await state.set_state(UserState.CHATTING)
    await message.answer(
        settings.texts.mode_selected.format(mode=mode),
        reply_markup=main_reply_keyboard(current_mode=mode),
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
            user_data = await state.get_data()
            mode = user_data.get("mode")
            if not mode:
                await status_message.delete()
                await message.answer(settings.texts.select_mode_first, reply_markup=main_reply_keyboard())
                return

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
            for file_path in downloaded_files:
                uploaded_file = await upload_file_to_gemini(file_path, api_key=api_key)
                if uploaded_file:
                    file_names.append(uploaded_file.name)

            if not file_names:
                await status_message.edit_text(settings.texts.media_error)
                return

            await state.update_data(file_names=file_names)
            user_content = " ".join(captions) if captions else settings.texts.photo_no_caption
            proxy_message = message.copy(update={'text': user_content, 'photo': None, 'caption': None})

            await handle_user_request(
                message=proxy_message, state=state, db_session=db_session, bot=bot,
                status_message=status_message, api_key=api_key
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
    mode: str, user_content: str, history: list, update_callback: callable, session: ClientSession, file_names: Optional[list[str]], api_key: str
) -> Tuple[Optional[GeminiResponse], Optional[str]]:
    expert_opinions = []
    ddg_queries = []
    expert_prompts = settings.prompts.experts

    for expert_name, expert_details in expert_prompts.items():
        await update_callback(f"Consulting {expert_name}...")
        expert_prompt = expert_details["prompt"]
        is_rag_expert = expert_details["rag"]

        # First call to get function call
        response = await generate_response(
            mode=mode, user_content=user_content, system_prompt=expert_prompt,
            history=history, is_rag_expert=is_rag_expert, file_names=file_names, api_key=api_key
        )

        opinion = None
        if response and response.function_calls:
            if is_rag_expert:
                # Assuming one function call for simplicity as in original logic
                call = response.function_calls[0]
                if call.name == "search_duckduckgo":
                    query = call.args.get("query", "")
                    ddg_queries.append(query)
                    await update_callback(f"Searching for: <code>{html.escape(query)}</code>")
                    
                    search_results = await get_instant_answer(query, session)

                    # The history already contains the initial user prompt
                    # We add the model's response (the function call) and the tool's response
                    model_turn_with_tool_call = {
                        "role": "model",
                        "parts": [{"function_call": call}]
                    }
                    tool_response_turn = {
                        "role": "tool",
                        "parts": [{
                            "function_response": {
                                "name": "search_duckduckgo",
                                "response": {"result": search_results}
                            }
                        }]
                    }
                    
                    # The original history, plus the user message that triggered the tool use, plus the tool use itself
                    new_history = history + [
                        {'role': 'user', 'parts': [user_content]},
                        model_turn_with_tool_call,
                        tool_response_turn
                    ]

                    # Second call to get the final opinion
                    final_expert_response = await generate_response(
                        mode=mode, 
                        user_content=None, # No new user content
                        system_prompt=expert_prompt,
                        history=new_history, 
                        is_rag_expert=is_rag_expert, 
                        file_names=file_names, 
                        api_key=api_key
                    )
                    opinion = final_expert_response.text
        else:
            opinion = response.text if response else None

        if opinion:
            expert_opinions.append(f"### {expert_name}'s Opinion:\n{opinion}")

    if not expert_opinions:
        return None, None

    await update_callback("Synthesizing opinions...")
    synthesizer_prompt = settings.prompts.synthesizer
    synthesis_context = "\n\n".join(expert_opinions)

    # Final synthesizer call
    final_response = await generate_response(
        mode=mode, user_content=synthesis_context, system_prompt=synthesizer_prompt,
        history=[], is_rag_expert=False, file_names=file_names, api_key=api_key
    )
    ddg_query_used = ", ".join(sorted(list(set(ddg_queries)))) if ddg_queries else None
    return final_response, ddg_query_used


@router.message(F.text, ~F.text.startswith('/'))
@log_user_action
async def handle_user_request(
    message: Message, state: FSMContext, db_session: Session, bot: Bot,
    status_message: Optional[Message] = None, api_key: Optional[str] = None
):
    user_id = message.from_user.id
    user_content = message.text

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
        except Exception:
            pass

    try:
        user_data = await state.get_data()
        mode = user_data.get("mode")
        file_names = user_data.get("file_names")

        user_db = get_or_create_user(db_session, user_id)
        chat_history = build_gemini_history(user_db, file_names is not None)

        response_obj, ddg_query_used = None, None

        if mode == "fast":
            system_prompt = settings.prompts.fast
            response_obj = await generate_response(
                mode=mode, user_content=user_content, system_prompt=system_prompt,
                history=chat_history, is_rag_expert=False, file_names=file_names, api_key=api_key
            )
        elif mode in ["reasoning", "agent"]:
            response_obj, ddg_query_used = await _run_experts_and_synthesizer(
                mode=mode, user_content=user_content, history=chat_history,
                update_callback=update_status, session=bot.session, file_names=file_names, api_key=api_key
            )

        final_text = response_obj.text if response_obj else settings.texts.error_message
        add_message_to_history(db_session, user_id, user_content, final_text, file_names)

        response_message = final_text
        if ddg_query_used:
            response_message += format_duckduckgo_html(ddg_query_used)

        await status_message.edit_text(response_message, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Error in handle_user_request for user {user_id}: {e}", exc_info=True)
        await status_message.edit_text(settings.texts.error_message)
