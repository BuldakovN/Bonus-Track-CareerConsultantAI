"""
Основной модуль Telegram бота
"""
import asyncio
import logging
import sys
import re
from typing import Dict, Any, Iterable, Optional
from aiogram import Bot, Dispatcher, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from common.error_logging import setup_service_error_logging
from config import config
from llm_client import LLMClient, LLMResponse

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
setup_service_error_logging("tg-module")


class TelegramBot:
    """Основной класс Telegram бота"""
    
    def __init__(self):
        if not config.validate():
            raise ValueError("Некорректная конфигурация бота")
        
        self.bot = Bot(token=config.bot_token)
        self.dp = Dispatcher()
        self.user_sessions: Dict[int, Dict[str, Any]] = {}
        
        # Регистрируем обработчики
        self._register_handlers()
        # self.point_glued_to_newline_bug_re = re.compile('\\n[]')
        self.point_glued_to_newline_bug_reverse_re = re.compile('\*\\n')
        self.md_spec_symb_remove_re = re.compile('\*{2}|#+')
        self.cleanup_re = re.compile(r'#+\s|\*\*')
        self.link_deletus_re = re.compile(r'\[.+\](?=\()')
        # self.bold_re = re.compile('(?<=\-).+(?=\:)')
    
    def _register_handlers(self):
        """Регистрирует все обработчики команд и сообщений"""
        
        # Обработчик команды /start
        @self.dp.message(CommandStart())
        async def start_handler(message: Message):
            await self._handle_start(message)
        
        # Обработчик команды /help
        @self.dp.message(Command("help"))
        async def help_handler(message: Message):
            await self._handle_help(message)

        # Обработчик команды /clean_history
        @self.dp.message(Command("clean_history"))
        async def cancel_handler(message: Message):
            await self._handle_clean_history(message)

        # Обработчик команды /status
        @self.dp.message(Command("status"))
        async def status_handler(message: Message):
            await self._handle_status(message)

        # Обработчик команды /status_local
        @self.dp.message(Command("status_local"))
        async def status_local_handler(message: Message):
            await self._handle_status_local(message)

        # Явное завершение теста (fallback, если клавиатура не отображается)
        @self.dp.message(Command("finish_test"))
        async def finish_test_handler(message: Message):
            await self._handle_finish_test_command(message)
        
        # Обработчик команды /cancel
        # @self.dp.message(Command("cancel"))
        # async def cancel_handler(message: Message):
        #     await self._handle_cancel(message)
        
        # Обработчик всех остальных сообщений
        @self.dp.message()
        async def message_handler(message: Message):
            await self._handle_message(message)
        
        # Обработчик callback-кнопок для профессий
        @self.dp.callback_query()
        async def callback_handler(callback_query: CallbackQuery):
            await self._handle_callback(callback_query)
    
    async def _handle_start(self, message: Message):
        """Обработчик команды /start"""
        user_id = message.from_user.id
        
        # Инициализируем сессию пользователя
        self.user_sessions[user_id] = {
            "active": True,
            "message_count": 0
        }

        # Показываем, что бот печатает
        await self.bot.send_chat_action(user_id, "typing")
        
        await self._answer_with_status(message, config.start_text, parse_mode="Markdown")
        async with LLMClient() as llm_client:
            llm_response = await llm_client.generate_response(
                "/start", user_id, parameters=self._request_parameters(message)
            )
            self._set_dialog_state(user_id, llm_response.user_state)
            await self._send_response_with_professions(message, llm_response)
        logger.info(f"Пользователь {user_id} запустил бота")
    
    async def _handle_help(self, message: Message):
        """Обработчик команды /help"""
        user_id = message.from_user.id

        # Показываем, что бот печатает
        await self.bot.send_chat_action(user_id, "typing")
        
        await self._answer_with_status(message, config.help_text)
        logger.info(f"Пользователь {user_id} запросил справку")

    async def _handle_clean_history(self, message: Message):
        """Обработчик команды /help"""
        user_id = message.from_user.id

        # Показываем, что бот печатает
        await self.bot.send_chat_action(user_id, "typing")
        async with LLMClient() as llm_client:
            response = await llm_client.clean_user_history(user_id)
            remove_keyboard = ReplyKeyboardRemove()

            # Сбрасываем процесс тестирования
            if self.user_sessions.get(user_id):
                self.user_sessions[user_id].pop("testing_process", None)
                self.user_sessions[user_id]["dialog_state"] = "who"
        await self._answer_with_status(message, response, parse_mode="Markdown", reply_markup=remove_keyboard)
        logger.info(f"Пользователь {user_id} запросил очистку истории")

    async def _handle_status(self, message: Message):
        """Показывает текущий статус диалога пользователя."""
        user_id = message.from_user.id
        await self.bot.send_chat_action(user_id, "typing")

        async with LLMClient() as llm_client:
            session = await llm_client.get_user_session(user_id)

        if not session:
            await self._answer_with_status(
                message,
                "Не удалось получить статус. Попробуйте повторить чуть позже.",
                parse_mode="Markdown",
            )
            return

        user_state = session.get("user_state") or "who"
        self._set_dialog_state(user_id, user_state)
        user_type = session.get("user_type") or "не определен"
        history_len = len(session.get("conversation_history") or [])
        metadata = session.get("user_metadata") or {}
        metadata_keys = ", ".join(sorted(metadata.keys())) if metadata else "нет"
        local_loaded = "да" if user_id in self.user_sessions else "нет"

        status_text = (
            "Текущий статус диалога:\n\n"
            f"- Фаза: `{user_state}`\n"
            f"- Тип пользователя: `{user_type}`\n"
            f"- Сообщений в истории: `{history_len}`\n"
            f"- Поля метаданных: `{metadata_keys}`\n"
            f"- Локальная сессия в боте: `{local_loaded}`"
        )
        await self._answer_with_status(message, status_text)
        logger.info("Пользователь %s запросил статус: state=%s", user_id, user_state)

    async def _handle_status_local(self, message: Message):
        """Показывает локальный статус пользователя только из памяти TelegramBot."""
        user_id = message.from_user.id
        await self.bot.send_chat_action(user_id, "typing")
        await self._sync_local_test_state(user_id)

        session = self.user_sessions.get(user_id)
        if not session:
            await self._answer_with_status(
                message,
                "Локальная сессия отсутствует в памяти бота для этого пользователя.",
                parse_mode="Markdown",
            )
            return

        active = session.get("active", False)
        message_count = session.get("message_count", 0)
        has_professions = bool(session.get("professions"))
        testing_process = session.get("testing_process") or {}
        testing_enabled = bool(testing_process.get("enabled"))
        awaiting_answer = bool(testing_process.get("awaiting_answer"))
        test_idx = testing_process.get("current_question_index")

        local_status_text = (
            "Локальный статус в TelegramBot:\n\n"
            f"- active: `{active}`\n"
            f"- message_count: `{message_count}`\n"
            f"- professions в сессии: `{has_professions}`\n"
            f"- dialog_state (кэш из графа): `{session.get('dialog_state')}`\n"
            f"- testing enabled: `{testing_enabled}`\n"
            f"- awaiting_answer: `{awaiting_answer}`\n"
            f"- current_question_index: `{test_idx}`"
        )
        await self._answer_with_status(message, local_status_text)
        logger.info("Пользователь %s запросил локальный статус", user_id)

    @staticmethod
    def _request_parameters(message: Message, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Параметры для core/CRUD: имя из Telegram и произвольные доп. поля."""
        p: Dict[str, Any] = {}
        if message.from_user:
            name = message.from_user.full_name or message.from_user.first_name or ""
            name = (name or "").strip()
            if name:
                p["user_display_name"] = name
        if extra:
            p.update(extra)
        return p

    @staticmethod
    def _state_to_emoji(state: Optional[str]) -> str:
        mapping = {
            "who": "👋",
            "about": "🧭",
            "test": "📝",
            "recommendation": "🎯",
            "talk": "💬",
            "inject_attempt": "🛡️",
        }
        return mapping.get((state or "").strip().lower(), "❓")

    def _set_dialog_state(self, user_id: int, state: Optional[str]) -> None:
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = {"active": True, "message_count": 0}
        if state:
            self.user_sessions[user_id]["dialog_state"] = str(state)

    async def _resolve_user_state(self, user_id: int) -> str:
        local_session = self.user_sessions.get(user_id) or {}
        cached_state = local_session.get("dialog_state")
        if cached_state:
            return str(cached_state)

        async with LLMClient() as llm_client:
            session = await llm_client.get_user_session(user_id)
        if session and session.get("user_state"):
            state = str(session.get("user_state"))
            self._set_dialog_state(user_id, state)
            return state
        return "who"

    async def _prefixed_status_text(self, user_id: int, text: str) -> str:
        state = await self._resolve_user_state(user_id)
        return f"{self._state_to_emoji(state)} {text}"

    async def _status_prefix(self, user_id: int) -> str:
        state = await self._resolve_user_state(user_id)
        return self._state_to_emoji(state)

    async def _answer_with_status(self, target_message: Message, text: str, **kwargs):
        prefixed = await self._prefixed_status_text(target_message.from_user.id, text)
        try:
            await target_message.answer(prefixed, **kwargs)
        except TelegramBadRequest as e:
            err = str(e).lower()
            # fallback: если текст ломает markdown/entities, отправляем plain text
            if "can't parse entities" not in err:
                raise
            safe_kwargs = dict(kwargs)
            safe_kwargs.pop("parse_mode", None)
            await target_message.answer(prefixed, **safe_kwargs)

    async def _sync_local_test_state(self, user_id: int) -> None:
        """
        Синхронизирует локальный testing_process из CRUD, если глобальная фаза = test.
        Нужен для случаев, когда локальная сессия уже была создана без теста.
        """
        local_session = self.user_sessions.get(user_id)
        if not local_session:
            return
        testing_process = local_session.get("testing_process") or {}
        if testing_process.get("enabled"):
            return

        async with LLMClient() as llm_client:
            session = await llm_client.get_user_session(user_id)
        if not session:
            return
        self._set_dialog_state(user_id, session.get("user_state"))
        if str(session.get("user_state") or "").lower() != "test":
            return

        user_metadata = session.get("user_metadata") or {}
        recommended_test = user_metadata.get("recommended_test")
        if not (
            isinstance(recommended_test, dict)
            and recommended_test.get("test_questions")
            and recommended_test.get("test_bottoms")
        ):
            return

        local_session["testing_process"] = {
            "enabled": True,
            "test_info": recommended_test,
            "answers": [],
            "awaiting_answer": False,
            "current_question_index": 0,
        }
        logger.info("Синхронизирован локальный testing_process из CRUD для пользователя %s", user_id)
    
    async def _handle_cancel(self, message: Message):
        """Обработчик команды /cancel"""
        user_id = message.from_user.id
        
        # Сбрасываем сессию пользователя
        if user_id in self.user_sessions:
            self.user_sessions[user_id]["active"] = False
        
        await self._answer_with_status(message, config.cancel_text, parse_mode="Markdown")
        logger.info(f"Пользователь {user_id} отменил операцию")

    async def _handle_finish_test_command(self, message: Message):
        user_id = message.from_user.id
        session = self.user_sessions.get(user_id) or {}
        testing_process = session.get("testing_process") or {}
        if testing_process.get("enabled"):
            await self.finish_test(message)
            return
        await self._answer_with_status(message, "Сейчас тест не запущен.")

    async def _handle_message(self, message: Message):
        """Обработчик обычных сообщений"""
        user_id = message.from_user.id
        user_message = message.text

        # Проверяем активность локальной сессии пользователя.
        # Если ее нет, пытаемся восстановить по данным из БД через CRUD.
        if user_id not in self.user_sessions:
            restored = await self._restore_session_from_db(user_id)
            if not restored:
                await self._answer_with_status(message, "Пожалуйста, начните с команды /start", parse_mode="Markdown")
                return

        if not self.user_sessions[user_id]["active"]:
            await self._answer_with_status(message, "Пожалуйста, начните с команды /start", parse_mode="Markdown")
            return

        await self._sync_local_test_state(user_id)

        # Если пользователь в процессе тестирования и ждет ответа
        if (self.user_sessions[user_id].get("testing_process") and
                self.user_sessions[user_id]["testing_process"]["enabled"] and
                self.user_sessions[user_id]["testing_process"].get("awaiting_answer")):
            await self._process_test_answer(message)
            return

        # Если тестирование включено, но не ждем ответа (начало теста)
        if self.user_sessions[user_id].get("testing_process") and self.user_sessions[user_id]["testing_process"][
            "enabled"]:
            await self.run_test(message)

        # Обычная обработка сообщения
        self.user_sessions[user_id]["message_count"] += 1

        typing_task = asyncio.create_task(self._show_typing_indicator(user_id))

        try:
            async with LLMClient() as llm_client:
                llm_response = await llm_client.generate_response(
                    user_message, user_id, parameters=self._request_parameters(message)
                )
                self._set_dialog_state(user_id, llm_response.user_state)

                if llm_response.test_info:
                    # Инициализируем процесс тестирования
                    self.user_sessions[user_id]["testing_process"] = {
                        "enabled": True,
                        "test_info": llm_response.test_info,
                        "answers": [],
                        "awaiting_answer": False
                    }
                    await self.run_test(message)
                else:
                    await self._send_response_with_professions(message, llm_response)
        except Exception as e:
            logger.error(f"Ошибка при генерации ответа: {e}")
            await self._answer_with_status(
                message,
                "Извините, произошла ошибка при обработке вашего сообщения.",
                parse_mode="Markdown",
            )
            typing_task.cancel()
            return

        logger.info(
            f"Отправлен ответ пользователю {user_id}, сообщение #{self.user_sessions[user_id]['message_count']}")
        typing_task.cancel()

    async def _restore_session_from_db(self, user_id: int) -> bool:
        """
        Пробует восстановить локальную сессию бота на основе данных CRUD.
        Возвращает True, если в БД есть признаки существующей сессии.
        """
        async with LLMClient() as llm_client:
            session = await llm_client.get_user_session(user_id)

        if not session:
            return False

        app_user_id = session.get("app_user_id")
        user_state = session.get("user_state")
        user_type = session.get("user_type")
        user_metadata = session.get("user_metadata") or {}
        conversation_history = session.get("conversation_history") or []

        # Считаем, что сессия существует, если пользователь уже зарегистрирован
        # в CRUD (app_user_id), либо есть признаки содержательного диалога:
        # история/метаданные/тип/не стартовая фаза.
        has_db_session = (
            app_user_id is not None
            or bool(conversation_history)
            or bool(user_metadata)
            or bool(user_type)
            or (user_state not in (None, "", "who"))
        )
        if not has_db_session:
            return False

        self.user_sessions[user_id] = {
            "active": True,
            "message_count": 0,
            "dialog_state": user_state or "who",
        }

        # Восстанавливаем локальный тестовый процесс из persisted-состояния.
        # Иначе /status показывает phase=test, а /status_local — testing disabled.
        recommended_test = user_metadata.get("recommended_test")
        if (
            str(user_state or "").lower() == "test"
            and isinstance(recommended_test, dict)
            and recommended_test.get("test_questions")
            and recommended_test.get("test_bottoms")
        ):
            self.user_sessions[user_id]["testing_process"] = {
                "enabled": True,
                "test_info": recommended_test,
                "answers": [],
                "awaiting_answer": False,
                "current_question_index": 0,
            }

        logger.info("Восстановлена локальная сессия из БД для пользователя %s", user_id)
        return True

    async def run_test(self, message: Message):
        user_id = message.from_user.id
        testing_process = self.user_sessions[user_id]["testing_process"]
        test_info = testing_process["test_info"]

        # Инициализируем состояние теста при первом запуске
        if "current_question_index" not in testing_process:
            testing_process["current_question_index"] = 0
            testing_process["answers"] = []
            testing_process["awaiting_answer"] = False
            
            # Отправляем описание теста
            test_desc = (f'Спасибо за ответы! Сейчас я проведу небольшой тест, чтобы на его основе подобрать профессии\n\n'
                         f'{test_info["test_description"]}')
            await self._answer_with_status(
                message,
                test_desc,
                parse_mode="Markdown"
            )

        current_idx = testing_process["current_question_index"]

        # Если мы ждем ответа на предыдущий вопрос, обрабатываем его
        if testing_process["awaiting_answer"]:
            await self._process_test_answer(message)
            return

        # Проверяем, есть ли еще вопросы
        if current_idx < len(test_info["test_questions"]):
            # Создаем клавиатуру с вариантами ответов
            buttons_list = test_info["test_bottoms"]
            builder = ReplyKeyboardBuilder()

            for test_button in buttons_list:
                builder.button(text=test_button)

            builder.row(KeyboardButton(text="🚫 Завершить тест"))
            keyboard = builder.as_markup(
                resize_keyboard=True,
                one_time_keyboard=False,
                is_persistent=True,
                input_field_placeholder="Выберите вариант ответа или завершите тест",
            )

            # Отправляем текущий вопрос
            await self._answer_with_status(
                message,
                test_info["test_questions"][current_idx],
                reply_markup=keyboard,
                parse_mode="Markdown"
            )

            # Устанавливаем флаг ожидания ответа
            testing_process["awaiting_answer"] = True

        else:
            # Все вопросы заданы, завершаем тест
            await self.finish_test(message)

    async def _process_test_answer(self, message: Message):
        user_id = message.from_user.id
        testing_process = self.user_sessions[user_id]["testing_process"]
        test_info = testing_process["test_info"]

        if message.text == "🚫 Завершить тест":
            await self.finish_test(message)
            return

        # Проверяем, что ответ является допустимым вариантом
        if message.text in test_info["test_bottoms"]:
            # Сохраняем ответ
            testing_process["answers"].append(message.text)

            # Увеличиваем счетчик вопроса
            testing_process["current_question_index"] += 1
            testing_process["awaiting_answer"] = False

            # Продолжаем со следующим вопросом или завершаем
            if testing_process["current_question_index"] < len(test_info["test_questions"]):
                await self.run_test(message)
            else:
                await self.finish_test(message)
        else:
            await self._answer_with_status(message, "Пожалуйста, выберите один из предложенных вариантов")

    async def finish_test(self, message: Message):
        user_id = message.from_user.id
        testing_process = self.user_sessions[user_id]["testing_process"]

        # Собираем результаты
        answers = testing_process["answers"]

        # Убираем клавиатуру
        remove_keyboard = ReplyKeyboardRemove()
        await self._answer_with_status(message, "Спасибо за прохождение теста!", reply_markup=remove_keyboard)
        await self._answer_with_status(message, "Формирую список рекомендаций, подождите немного…")

        # Сбрасываем процесс тестирования
        questions = self.user_sessions[user_id]['testing_process']['test_info']['test_questions']
        self.user_sessions[user_id]["testing_process"] = {
            "enabled": False,
            "test_info": None
        }
        async with LLMClient() as llm_client:
            llm_response = await llm_client.generate_response(
                "",
                user_id,
                parameters=self._request_parameters(
                    message,
                    {"test_results": list(zip(questions, answers))},
                ),
            )
            self._set_dialog_state(user_id, llm_response.user_state)
            await self._send_response_with_professions(message, llm_response)



    async def _send_response_with_professions(self, original_message: Message, llm_response: LLMResponse):
        """
        Отправляет ответ от LLM с кнопками профессий, если они есть
        
        Args:
            original_message: Исходное сообщение пользователя
            llm_response: Ответ от LLM с текстом и профессиями
        """
        logger.info(f"🔍 Отправляем ответ с профессиями. Профессии: {llm_response.professions}")
        self._set_dialog_state(original_message.from_user.id, llm_response.user_state)
        
        # Сначала отправляем основное сообщение
        await self._send_long_message(original_message, llm_response.msg)
        
        # Если есть профессии, создаем кнопки
        if llm_response.professions:
            logger.info(f"Создаем кнопки для {len(llm_response.professions)} профессий")
            builder = InlineKeyboardBuilder()
            
            user_id = original_message.from_user.id
            if user_id not in self.user_sessions:
                self.user_sessions[user_id] = {"active": True, "message_count": 0}
            
            # Создаем мапинг профессий с индексами
            profession_list = list(llm_response.professions.items())
            self.user_sessions[user_id]["professions"] = profession_list
            
            for index, (profession_name, profession_description) in enumerate(profession_list):
                # Используем короткий индекс как callback_data
                builder.button(
                    text=profession_name,
                    callback_data=f"prof:{index}"
                )
                logger.info(f"➕ Добавлена кнопка: {profession_name} (индекс: {index})")
            
            # Располагаем кнопки по 2 в ряд
            builder.adjust(2)
            
            await self._answer_with_status(
                original_message,
                "💼 Выберите интересующую профессию для получения подробной информации:",
                reply_markup=builder.as_markup(),
                parse_mode="Markdown"
            )
            logger.info("✅ Кнопки отправлены")
        else:
            logger.info("ℹ️ Профессии отсутствуют, кнопки не создаем")
    
    async def _handle_callback(self, callback_query: CallbackQuery):
        """Обработчик callback-кнопок"""
        user_id = callback_query.from_user.id
        callback_data = callback_query.data
        
        # Подтверждаем получение callback
        await callback_query.answer()
        
        if callback_data == "back_to_professions":
            await self._show_professions_list(callback_query)
        else:
            try:
                # Извлекаем индекс профессии
                profession_index = int(callback_data.replace("prof:", "").replace("road:", ""))
                
                # Получаем профессию из сессии пользователя
                if (user_id in self.user_sessions and 
                    "professions" in self.user_sessions[user_id] and
                    0 <= profession_index < len(self.user_sessions[user_id]["professions"])):
                    
                    profession_name, profession_description = self.user_sessions[user_id]["professions"][profession_index]
                    if callback_data.startswith("prof:"):
                        await self._show_profession_details(callback_query, profession_name, profession_index)
                    elif callback_data.startswith("road:"):
                        await self._show_profession_roadmap(callback_query, profession_name)
                    else:
                        raise NotImplementedError
                else:
                    await self._answer_with_status(
                        callback_query.message,
                        "❌ Профессия не найдена. Попробуйте еще раз.",
                        parse_mode="Markdown",
                    )
                    logger.error(f"Профессия с индексом {profession_index} не найдена для пользователя {user_id}")
                    
            except (ValueError, IndexError, NotImplementedError) as e:
                await self._answer_with_status(
                    callback_query.message,
                    "❌ Ошибка при обработке выбора профессии.",
                    parse_mode="Markdown",
                )
                logger.error(f"Ошибка обработки callback {callback_data}: {e}")
                if isinstance(e, NotImplementedError):
                    logger.error(f"Возникло неожиданное значение в callback кнопки: {callback_data}")
                    

    
    async def _show_profession_roadmap(self, callback_query: CallbackQuery, profession_name: str):
        """Показывает подробное описание профессии через RAG систему"""
        user_id = callback_query.from_user.id
        
        # Показываем, что бот обрабатывает запрос
        typing_task = asyncio.create_task(self._show_typing_indicator(user_id))

        # Создаем кнопку "Назад к списку профессий" даже при ошибке
        builder = InlineKeyboardBuilder()
        builder.button(
            text="🔙 Назад к списку профессий",
            callback_data="back_to_professions"
        )

        try:
            # Запрашиваем у LLM подробное описание профессии через RAG
            async with LLMClient() as llm_client:
                llm_response = await llm_client.get_profession_roadmap(profession_name, user_id)

                # Отправляем описание профессии с кнопкой "Назад"
                await self._send_long_message(callback_query.message, llm_response.msg, builder)

        except Exception as e:
            typing_task.cancel()
            logger.error(f"Ошибка при получении описания профессии {profession_name}: {e}")
            
            await self._answer_with_status(
                callback_query.message,
                f"📋 **{profession_name}**\n\nИзвините, не удалось получить подробное описание этой профессии.",
                reply_markup=builder.as_markup(),
                parse_mode="Markdown"
            )
        
        logger.info(f"Пользователь {user_id} запросил описание профессии: {profession_name}")
        typing_task.cancel()

    async def _show_profession_details(self, callback_query: CallbackQuery, profession_name: str, prof_index: int):
        """Показывает подробное описание профессии через RAG систему"""
        user_id = callback_query.from_user.id
        
        # Показываем, что бот обрабатывает запрос
        typing_task = asyncio.create_task(self._show_typing_indicator(user_id))

        # Создаем кнопку "Назад к списку профессий" даже при ошибке
        builder = InlineKeyboardBuilder()
        builder.button(
            text="🔙 Назад к списку профессий",
            callback_data="back_to_professions"
        )

        try:
            # Запрашиваем у LLM подробное описание профессии через RAG
            async with LLMClient() as llm_client:
                llm_response = await llm_client.get_profession_info(profession_name, user_id)
                builder.button(
                    text="📈 Показать роудмап",
                    callback_data=f"road:{prof_index}"
                )
                # Отправляем описание профессии с кнопкой "Назад"
                await self._send_long_message(callback_query.message, llm_response.msg, builder)

        except Exception as e:
            typing_task.cancel()
            logger.error(f"Ошибка при получении описания профессии {profession_name}: {e}")
            
            await self._answer_with_status(
                callback_query.message,
                f"📋 **{profession_name}**\n\nИзвините, не удалось получить подробное описание этой профессии.",
                reply_markup=builder.as_markup(),
                parse_mode="Markdown"
            )
        
        logger.info(f"Пользователь {user_id} запросил описание профессии: {profession_name}")
        typing_task.cancel()
    
    async def _show_professions_list(self, callback_query: CallbackQuery):
        """Показывает список профессий с кнопками"""
        user_id = callback_query.from_user.id
        
        # Проверяем, есть ли сохраненные профессии в сессии пользователя
        if (user_id in self.user_sessions and 
            "professions" in self.user_sessions[user_id] and
            self.user_sessions[user_id]["professions"]):
            
            professions = self.user_sessions[user_id]["professions"]
            builder = InlineKeyboardBuilder()
            
            # Создаем кнопки для всех профессий
            for index, (profession_name, profession_description) in enumerate(professions):
                builder.button(
                    text=profession_name,
                    callback_data=f"prof:{index}"
                )
            
            # Располагаем кнопки по 2 в ряд
            builder.adjust(2)
            
            # Редактируем сообщение с кнопкой "Назад", убирая её и показывая список профессий
            try:
                await callback_query.message.edit_text(
                    await self._prefixed_status_text(
                        user_id,
                        "💼 Выберите интересующую профессию для получения подробной информации:",
                    ),
                    reply_markup=builder.as_markup(),
                    parse_mode="Markdown"
                )
                logger.info(f"Пользователь {user_id} вернулся к списку профессий")
            except Exception as e:
                # Если редактирование не удалось, отправляем новое сообщение
                logger.warning(f"Не удалось отредактировать сообщение: {e}")
                await self._answer_with_status(
                    callback_query.message,
                    "💼 Выберите интересующую профессию для получения подробной информации:",
                    reply_markup=builder.as_markup(),
                    parse_mode="Markdown"
                )
                logger.info(f"Пользователь {user_id} вернулся к списку профессий (новое сообщение)")
        else:
            # Если профессии не найдены, отправляем сообщение об ошибке
            await self._answer_with_status(
                callback_query.message,
                "❌ Список профессий не найден. Попробуйте начать новый диалог с помощью команды /start",
                parse_mode="Markdown"
            )
            logger.warning(f"Профессии не найдены для пользователя {user_id}")

    def sanitize_text(self, text):
        text = self.cleanup_re.sub('', text)
        text = text.replace('*', '-')
        text = self.link_deletus_re.sub('', text)
        return text

    async def _send_long_message(self, original_message: Message, text: str, buttons: InlineKeyboardBuilder = None):
        """
        Отправляет длинное сообщение, разбивая его на части если необходимо

        Args:
            original_message: Исходное сообщение пользователя
            text: Текст для отправки
        """
        text = self.sanitize_text(text)
        prefix = await self._status_prefix(original_message.from_user.id)
        # if len(text) <= config.max_message_length:
        #     if buttons:
        #         await original_message.answer(text, parse_mode="Markdown", reply_markup=buttons.as_markup())
        #     else:
        #         await original_message.answer(text, parse_mode="Markdown")
        #     return

        # Просто разбиваем текст на куски фиксированной длины
        parts = []
        for i in range(0, len(text), config.max_message_length):
            part = text[i:i + config.max_message_length]
            parts.append(part)

        # Отправляем все части
        for i, part in enumerate(parts):
            if i > 0:
                await asyncio.sleep(config.message_delay)
            # прикрепляем кнопку к последнему сообщению
            part_with_prefix = f"{prefix} {part}"
            if i == len(parts) - 1 and buttons:
                await original_message.answer(part_with_prefix, reply_markup=buttons.as_markup())
            else:
                await original_message.answer(part_with_prefix)

    async def _show_typing_indicator(self, user_id):
        """Показывать индикатор набора каждые 3 секунды пока не отменят"""
        while True:
            try:
                await self.bot.send_chat_action(user_id, "typing")
                await asyncio.sleep(3)  # Telegram показывает 5 секунд
            except asyncio.CancelledError:
                break
            except Exception:
                break
    
    async def start_polling(self):
        """Запускает бота в режиме polling"""
        logger.info("Запуск бота...")
        try:
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {e}")
            raise
    
    async def stop(self):
        """Останавливает бота"""
        logger.info("Остановка бота...")
        await self.bot.session.close()

# Функция для запуска бота
async def main():
    """Основная функция для запуска бота"""
    bot = TelegramBot()
    
    try:
        await bot.start_polling()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        await bot.stop()

if __name__ == "__main__":
    asyncio.run(main())
