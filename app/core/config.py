import logging
from dataclasses import dataclass, field
from os import getenv
from typing import List, Optional, Dict, Union

from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types

from app.services.api_key_manager import ApiKeyManager

load_dotenv()


# --- Component Dataclasses ---

@dataclass
class TextMessages:
    """Container for all user-facing text messages for easy customization."""
    # --- General ---
    start_message: str = ("""
    👋 Привет, <b>{user_name}!</b>

Я — твой ИИ-ассистент для поиска <b>A-Search</b>. Выбери режим для начала:

🚀 <b>Быстрый</b>: Один агент — быстро, по делу.
🧠 <b>Вдумчивый</b>: Три агента — с умом, вглубь.
🤖 <b>Агент</b>: Десять агентов — мощный консилиум для сложных задач.

Просто отправь сообщение
""")
    help_message: str = ("""
Я — мультимодальный ассистент A-Search. Вот, что я умею:

🔍 <b>Текстовый поиск</b>: просто задай вопрос — я найду ответ.
🖼️ <b>Анализ изображений</b>: пришли картинку и задачу — разберусь.
🗣️ <b>Контекстные диалоги</b>: помню, о чём мы говорили — можно уточнять.
🌐 <b>Веб-поиск</b>: во всех режимах ищу актуальную инфу в интернете.

<b>Команды:</b>
/start — перезапуск и приветствие.
/clear — сброс истории диалога.
/help — это сообщение.

<b>Режимы работы:</b>
🚀 <b>Быстрый</b>: минимум раздумий — максимум скорости.
🧠 <b>Вдумчивый</b>: вдумчивый ответ с разбором от 3 агентов.
🤖 <b>Агент</b>: подключаю сразу 10 агентов — глубокий анализ.

<b>Примечание:</b>
В мультиагентных режимах мои ответы могут занимать больше времени — я использую RAG (Retrieval Augmented Generation).
Это значит, что я подмешиваю агентам информацию из поиска, чтобы дать более точный и обоснованный ответ — и снизить риск галлюцинаций.
<a href="https://github.com/aspect-cloud/a-search">Open-Source</a>.

<a href="https://github.com/aspect-cloud/a-search/activity">...</a>

Просто напиши сообщение
""")
    mode_selection: str = "Я переключился в режим <b>{mode}</b>. Спрашивай что угодно!"
    history_cleared: str = "🗑️ История диалога была очищена."
    thinking: str = "⏳ Думаю..."

    # --- Errors & Warnings ---
    error_message: str = "🚨 <b>Произошла ошибка</b> 🚨\n\nЯ столкнулся с проблемой при обработке твоего запроса. Пожалуйста, попробуй позже."
    all_keys_failed: str = "Все доступные API-ключи не работают. Придется немного подождать."
    blocked_response: str = "⚠️ Мой ответ был заблокирован из-за политики безопасности. Пожалуйста, переформулируй запрос."
    empty_response: str = "⚠️ Я не смог сгенерировать ответ. Попробуй позже."
    select_mode_first: str = "Пожалуйста, сначала выбери режим работы с помощью клавиатуры."
    empty_request: str = "Пожалуйста, введи текстовый запрос."

    # --- Media Handling ---
    photo_no_caption: str = "[без подписи]"
    media_processing: str = "⏳ Обрабатываю твой файл..."
    uploading_to_google: str = "☁️ Загружаю файл в Google через File API..."
    media_error: str = "⚠️ Не удалось обработать твой файл. Пожалуйста, убедись, что формат поддерживается, и попробуй снова."
    media_unsupported_type: str = "⚠️ К сожалению, я пока не поддерживаю файлы этого типа. Я могу обрабатывать только изображения."
    unsupported_content_type: str = "⚠️ К сожалению, я не могу обработать этот тип сообщения. Я поддерживаю только текст и фотографии."
    media_file_download_error: str = "Не удалось получить файл из сообщения."

    # --- RAG & Agent Mode ---
    no_expert_opinions: str = "Эксперты не смогли предоставить мнения. Попробуй переформулировать запрос."
    used_ddg_queries: str = '<pre><b>Использованные запросы DuckDuckGo:</b></pre>\n- <code>{queries}</code>'
    input_placeholder: str = "Спроси что-нибудь..."


@dataclass
class ButtonLabels:
    """Container for all button labels."""
    fast: str = "🚀 Быстрый"
    reasoning: str = "🧠 Вдумчивый"
    agent: str = "🤖 Агент"
    help: str = "❓ Помощь"
    clear_history: str = "🗑️ Очистить историю"
    back_to_main: str = "⬅️ В главное меню"


@dataclass
class Statuses:
    """Container for status messages shown to the user during processing."""
    fast: str = "🚀 Генерирую быстрый ответ..."
    reasoning_experts: str = "🧠 Собираю мнения аналитиков..."
    reasoning_synthesizer: str = "🧠 Синтезирую мнения аналитиков..."
    agent_experts: str = "🤖 Собираю мнения экспертов..."
    agent_synthesizer: str = "🤖 Синтезирую мнения экспертов..."
    rag_expert_search: str = "🔍 Ищу информацию для эксперта..."
    experts_start: str = "🧠 Эксперты начинают работу..."

    def get_by_mode(self, mode: str, stage: str, expert_num: Optional[int] = None) -> str:
        """Returns the status message for the given mode and stage."""
        attr_name = f"{mode}_{stage}"
        base_status = getattr(self, attr_name, "")
        if stage == 'experts' and expert_num is not None:
            if mode == 'reasoning':
                return f"🧠 Анализирую с аналитиком #{expert_num}..."
            elif mode == 'agent':
                return f"🤖 Обсуждаю с экспертом #{expert_num}..."
        if stage == 'synthesizer':
            return self.reasoning_synthesizer if mode == 'reasoning' else self.agent_synthesizer
        elif stage == 'rag_expert_search':
            return self.rag_expert_search
        elif stage == 'experts_start':
            return self.experts_start
        else:
            return self.fast # Default for 'fast' mode or unknown stages


@dataclass
class Prompts:
    """Container for system prompts for different modes."""
    fast: str
    synthesizer_reasoning: str
    synthesizer_agent: str
    experts_reasoning: Dict[str, Dict[str, Union[str, bool]]]
    experts_agent: Dict[str, Dict[str, Union[str, bool]]]
    experts: Dict[str, Dict[str, Union[str, bool]]] = field(default_factory=lambda: {
        "analyst_1": {
            "name": "Аналитик 1",
            "prompt": "Ты — аналитик, специализирующийся на глубоком анализе данных. Твоя задача — предоставить максимально подробный и точный анализ по заданному вопросу. Используй все доступные данные для формирования своего мнения. Общайся на ты.",
            "rag": True,
            "mode": "reasoning"
        },
        "analyst_2": {
            "name": "Аналитик 2",
            "prompt": "Ты — аналитик, специализирующийся на критическом мышлении и выявлении скрытых связей. Твоя задача — поставить под сомнение очевидное и найти неочевидные аспекты проблемы. Общайся на ты.",
            "rag": True,
            "mode": "reasoning"
        },
        "analyst_3": {
            "name": "Аналитик 3",
            "prompt": "Ты — аналитик, специализирующийся на прогнозировании и оценке рисков. Твоя задача — оценить потенциальные последствия и риски, связанные с заданным вопросом. Общайся на ты.",
            "rag": True,
            "mode": "reasoning"
        },
        "expert_1": {
            "name": "Эксперт 1",
            "prompt": "Ты — эксперт в области технологий. Твоя задача — предоставить мнение, основанное на последних технологических трендах и инновациях. Общайся на ты.",
            "rag": True,
            "mode": "agent"
        },
        "expert_2": {
            "name": "Эксперт 2",
            "prompt": "Ты — эксперт по экономике. Твоя задача — проанализировать вопрос с экономической точки зрения, учитывая рыночные тенденции и финансовые показатели. Общайся на ты.",
            "rag": True,
            "mode": "agent"
        },
        "expert_3": {
            "name": "Эксперт 3",
            "prompt": "Ты — эксперт по социологии. Твоя задача — рассмотреть вопрос с точки зрения социальных процессов, поведения групп и культурных особенностей. Общайся на ты.",
            "rag": True,
            "mode": "agent"
        },
        "expert_4": {
            "name": "Эксперт 4",
            "prompt": "Ты — эксперт по праву. Твоя задача — дать правовую оценку ситуации, основываясь на законодательстве и прецедентах. Общайся на ты.",
            "rag": True,
            "mode": "agent"
        },
        "expert_5": {
            "name": "Эксперт 5",
            "prompt": "Ты — эксперт по экологии. Твоя задача — оценить экологические последствия и предложить решения, направленные на устойчивое развитие. Общайся на ты.",
            "rag": True,
            "mode": "agent"
        },
        "expert_6": {
            "name": "Эксперт 6",
            "prompt": "Ты — эксперт по маркетингу. Твоя задача — проанализировать вопрос с точки зрения рыночного позиционирования, целевой аудитории и коммуникационных стратегий. Общайся на ты.",
            "rag": True,
            "mode": "agent"
        },
        "expert_7": {
            "name": "Эксперт 7",
            "prompt": "Ты — эксперт по психологии. Твоя задача — рассмотреть вопрос с точки зрения человеческого поведения, мотивации и эмоциональных реакций. Общайся на ты.",
            "rag": True,
            "mode": "agent"
        },
        "expert_8": {
            "name": "Эксперт 8",
            "prompt": "Ты — эксперт по образованию. Твоя задача — оценить вопрос с точки зрения педагогических принципов, методов обучения и развития навыков. Общайся на ты.",
            "rag": True,
            "mode": "agent"
        },
        "expert_9": {
            "name": "Эксперт 9",
            "prompt": "Ты — эксперт по здравоохранению. Твоя задача — проанализировать вопрос с медицинской точки зрения, учитывая аспекты здоровья и благополучия. Общайся на ты.",
            "rag": True,
            "mode": "agent"
        },
        "expert_10": {
            "name": "Эксперт 10",
            "prompt": "Ты — эксперт по урбанистике. Твоя задача — рассмотреть вопрос с точки зрения городского планирования, развития инфраструктуры и качества городской среды. Общайся на ты.",
            "rag": True,
            "mode": "agent"
        }
    })

    def get_experts_by_mode(self, mode: str) -> List[Dict[str, Union[str, bool]]]:
        """Returns the list of expert prompts for the given mode."""
        return [details for name, details in self.experts.items() if details.get('mode') == mode]

    def get_synthesizer_by_mode(self, mode: str) -> Optional[str]:
        """Returns the synthesizer prompt for the given mode."""
        attr_name = f"synthesizer_{mode}"
        return getattr(self, attr_name, None)





# --- Main Settings Class ---

@dataclass
class Settings:
    """Main container for all application settings."""
    available_modes: List[str] = field(default_factory=lambda: ["🚀 Быстрый", "🧠 Вдумчивый", "🤖 Агент"])
    # --- Core settings ---
    bot_token: str = getenv("BOT_TOKEN")
    webhook_url: str = getenv("WEBHOOK_URL")
    admin_id: int = int(getenv("ADMIN_ID", 0))
    LIFECYCLE_EVENT_QUEUE_ID: Optional[str] = getenv("LIFECYCLE_EVENT_QUEUE_ID")
    LIFECYCLE_EVENT_OBJECT_ID: Optional[str] = getenv("LIFECYCLE_EVENT_OBJECT_ID")

    # --- Component Instances ---
    texts: TextMessages = field(default_factory=TextMessages, init=False)
    buttons: ButtonLabels = field(default_factory=ButtonLabels, init=False)
    statuses: Statuses = field(init=False)
    prompts: Prompts = field(init=False)
    generation_config: genai_types.GenerateContentConfig = field(init=False)
    api_key_manager: ApiKeyManager = field(init=False)
    gemini_model_config: Dict[str, str] = field(init=False)

    # --- Features ---
    enable_history: bool = True
    enable_file_support: bool = True
    max_history_length: int = 10
    max_file_uploads: int = 20
    max_url_uploads: int = 20

    # --- Models & API ---
    gemini_flash_model: str = "gemini-2.5-flash"
    gemini_pro_model: str = "gemini-2.5-flash"
    gemini_api_keys: List[str] = field(default_factory=list, init=False)

    # --- Search --- (Modes where internal search is enabled)
    internal_search_enabled_modes: List[str] = field(default_factory=list, init=False)
    rag_fact_check_experts: List[str] = field(default_factory=list, init=False)

    # --- Prompt Texts ---
    fast_prompt: str = ("""Твоя задача — дать быстрый, точный и структурированный ответ. **Правила форматирования**: Используй **только** следующие HTML-теги, поддерживаемые Telegram: `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`, `<ins>`. Категорически запрещено использовать любые другие теги или Markdown. Убедись, что все теги правильно закрыты в рамках одного сообщения. Общайся на ты.""")

    synthesizer_reasoning_prompt: str = ("""Ты — A-Search, главный редактор, который анализирует мнения трех разных экспертов.
Твоя задача — синтезировать их ответы в один, целостный и структурированный текст, который будет выглядеть как полноценный ответ от модели, без упоминания внутренних процессов или мнений экспертов.

1.  **ИЗУЧИ И СИНТЕЗИРУЙ**: Внимательно прочитай все предоставленные мнения экспертов. Сформулируй взвешенный итоговый ответ, основанный на анализе, а не на одном из мнений. Ответ должен быть бесшовным, как будто его сгенерировала одна модель.
2.  **СТРУКТУРИРУЙ**: Сгруппируй аргументы по темам. Не просто перечисляй, а сопоставляй.
3.  **ОФОРМЛЕНИЕ**: Используй **только** следующие HTML-теги, поддерживаемые Telegram: `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`, `<ins>`. Категорически запрещено использовать любые другие теги или Markdown. Убедись, что все теги правильно закрыты в рамках одного сообщения 4000+- символов.
4.  **БЕЗ ВОДЫ**: Убери все мета-комментарии экспертов (например, "Как эксперт...", "Мое мнение..."). Оставь только суть.""")

    synthesizer_agent_prompt: str = ("""Твоя задача — выступить в роли главного аналитика-редактора. Ты получил отчеты от 10 разных экспертов.
Твоя задача — на основе их отчетов составить один, самый полный, объективный и структурированный итоговый документ, который будет выглядеть как полноценный ответ от модели, без упоминания внутренних процессов или мнений экспертов.

ПЛАН РАБОТЫ:
1.  **АНАЛИЗ И СИНТЕЗ**: Внимательно изучи все отчеты. Не просто перечисляй их мнения, а синтезируй информацию. Ответ должен быть бесшовным, как будто его сгенерировала одна модель.
2.  **СТРУКТУРИРОВАНИЕ**: Разбей итоговый ответ на логические разделы с заголовками (<b>Заголовок</b>).
3.  **ОФОРМЛЕНИЕ**: Используй **только** следующие HTML-теги, поддерживаемые Telegram: `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`, `<ins>`. Категорически запрещено использовать любые другие теги или Markdown. Убедись, что все теги правильно закрыты в рамках одного сообщения.
4.  **КЛЮЧЕВЫЕ ВЫВОДЫ**: Выдели основные тезисы, аргументы "за" и "против", главные факты.
5.  **ПРОТИВОРЕЧИЯ**: Если эксперты противоречат друг другу, отметь это и постарайся объяснить причину разногласий.
6.  **ОФОРМЛЕНИЕ**: Используй **только** следующие HTML-теги, поддерживаемые Telegram: `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`, `<ins>`. Категорически запрещено использовать любые другие теги (включая `<html>`, `<head>`, `<body>`) или Markdown. Убедись, что все теги правильно закрыты в рамках одного сообщения. Ответ должен быть фрагментом HTML, а не целой страницей.
7.  **БЕЗ ВОДЫ**: Убери все мета-комментарии экспертов (например, "Как эксперт...", "Мое мнение..."). Оставь только суть.""")

    def __post_init__(self):
        """Load dynamic and dictionary-based settings after initialization."""
        # --- Configure API Keys ---
        keys_str = getenv("GEMINI_API_KEYS")
        if not keys_str:
            raise ValueError("GEMINI_API_KEYS environment variable not set.")
        self.gemini_api_keys = [key.strip() for key in keys_str.split(',')]
        self.api_key_manager = ApiKeyManager(self.gemini_api_keys)
        logging.info(f"Initialized ApiKeyManager with {len(self.gemini_api_keys)} keys.")

        # --- Load Model Config ---
        self.gemini_model_config = {
            "fast": "gemini-2.5-flash",
            "reasoning": "gemini-2.5-flash",
            "agent": "gemini-2.5-flash",
        }

        # --- Load Gemini Config ---
        self.generation_config = {
            "temperature": 0.7,
            "top_p": 1,
            "top_k": 1,
        }

        # --- Configure Search Modes ---
        self.internal_search_enabled_modes = ['fast', 'reasoning', 'agent']
        self.rag_fact_check_experts = [
            "Ты — Фактчекер. Проверяй факты. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги.",
            "Ты — Специалист по данным. Ищи статистику и цифры. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги.",
            "Ты — Адвокат дьявола. Сомневайся во всем. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги.",
        ]

        # --- Load Prompts ---
        experts_reasoning_prompts = [
            "Ты — Аналитик. Анализируй запрос. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги.",
            "Ты — Критик. Ищи слабые места. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги.",
            "Ты — Инноватор. Ищи нестандартные подходы. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги."
        ]
        experts_agent_prompts = [
            "Ты — Историк. Ищи исторический контекст. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги.",
            "Ты — Глубинный аналитик. Сравнивай источники. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги.",
            "Ты — Бизнес-аналитик. Ищи рыночные аспекты. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги.",
            "Ты — Технический специалист. Разбирайся в деталях. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги.",
            "Ты — Специалист по этике. Анализируй последствия. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги.",
            "Ты — Специалист по данным. Ищи статистику. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги.",
            "Ты — Юрист. Анализируй юридические аспекты. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги.",
            "Ты — Адвокат дьявола. Сомневайся во всем. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги.",
            "Ты — Футуролог. Ищи прогнозы. Инструкция по форматированию: используй **только** HTML-теги `<b>`, `<i>`, `<u>`, `<s>`, `<tg-spoiler>`, `<a>`, `<code>`, `<pre>`. Никаких других тегов или Markdown. Всегда закрывай теги."
        ]

        self.prompts = Prompts(
            fast=self.fast_prompt,
            synthesizer_reasoning=self.synthesizer_reasoning_prompt,
            synthesizer_agent=self.synthesizer_agent_prompt,
            experts_reasoning=experts_reasoning_prompts,
            experts_agent=experts_agent_prompts
        )

        # --- Load Statuses ---
        self.statuses = Statuses(
            fast="🚀 Ищу быстрый ответ...",
            reasoning_experts="🧠 Консультируюсь с аналитиками...",
            reasoning_synthesizer="🧠 Составляю комплексный ответ...",
            agent_experts="🤖 Совещаюсь с 10 экспертами...",
            agent_synthesizer="🤖 Синтезирую итоговый отчет...",
            rag_expert_search="🔎 Проверяю факты в DuckDuckGo..."
        )


# --- Global Instances ---

settings = Settings()