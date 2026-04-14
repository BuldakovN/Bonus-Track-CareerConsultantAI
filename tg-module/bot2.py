"""
Refactored Telegram bot module.
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from common.error_logging import setup_service_error_logging
from config import config
from llm_client import LLMClient, LLMResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
setup_service_error_logging("tg-module")


STATE_EMOJI = {
    "who": "👋",
    "about": "🧭",
    "test": "📝",
    "recommendation": "🎯",
    "talk": "💬",
    "inject_attempt": "🛡️",
}

FINISH_TEST_BUTTON = "🚫 Завершить тест"
PROF_LIST_TEXT = "💼 Выберите интересующую профессию для получения подробной информации:"


@dataclass
class UserSession:
    active: bool = True
    message_count: int = 0
    dialog_state: str = "who"
    professions: List[Tuple[str, str]] = field(default_factory=list)
    # test_run_version из последнего ответа core, если user_state был test
    test_version_from_core: Optional[str] = None


class SafeMessageSender:
    """
    Sends messages with:
    - markdown parse fallback (disable parse mode on parse errors),
    - long text splitting with markdown-safe boundaries.
    """

    def __init__(self, max_len: int, delay: float) -> None:
        self.max_len = max_len
        self.delay = delay

    async def send(
        self,
        message: Message,
        text: str,
        prefix: str,
        parse_mode: Optional[str] = "Markdown",
        reply_markup: Any = None,
    ) -> None:
        content = f"{prefix} {text}".strip()
        if len(content) <= self.max_len:
            await self._send_single(message, content, parse_mode=parse_mode, reply_markup=reply_markup)
            return

        chunks = self._split_markdown(content, self.max_len)
        for index, chunk in enumerate(chunks):
            if index > 0:
                await asyncio.sleep(self.delay)
            last_markup = reply_markup if index == len(chunks) - 1 else None
            await self._send_single(message, chunk, parse_mode=parse_mode, reply_markup=last_markup)

    async def _send_single(
        self,
        message: Message,
        text: str,
        parse_mode: Optional[str],
        reply_markup: Any,
    ) -> None:
        try:
            await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
        except TelegramBadRequest as exc:
            if "can't parse entities" not in str(exc).lower():
                raise
            await message.answer(text, reply_markup=reply_markup)

    def _split_markdown(self, text: str, limit: int) -> List[str]:
        if len(text) <= limit:
            return [text]

        chunks: List[str] = []
        remaining = text

        while len(remaining) > limit:
            split_at = self._best_split_position(remaining, limit)
            if split_at <= 0:
                split_at = limit
            chunk = remaining[:split_at].rstrip()
            if not chunk:
                chunk = remaining[:limit]
                split_at = limit
            chunks.append(chunk)
            remaining = remaining[split_at:].lstrip()

        if remaining:
            chunks.append(remaining)
        return chunks

    def _best_split_position(self, text: str, limit: int) -> int:
        candidates = [m.start() for m in re.finditer(r"\n\n|\n|\. |\! |\? |, | ", text[:limit])]
        if not candidates:
            return limit

        # choose the rightmost markdown-safe candidate
        for pos in reversed(candidates):
            left = text[:pos]
            if self._is_markdown_balanced(left):
                return pos
        return candidates[-1]

    @staticmethod
    def _is_markdown_balanced(text: str) -> bool:
        # Keep splitter conservative to avoid breaking inline markdown.
        # This covers the most common parse breakers.
        star = text.count("*") % 2 == 0
        under = text.count("_") % 2 == 0
        backtick = text.count("`") % 2 == 0
        square = text.count("[") == text.count("]")
        paren = text.count("(") == text.count(")")
        return star and under and backtick and square and paren


class TelegramBot:
    def __init__(self) -> None:
        if not config.validate():
            raise ValueError("Некорректная конфигурация бота")

        self.bot = Bot(token=config.bot_token)
        self.dp = Dispatcher()
        self.user_sessions: Dict[int, UserSession] = {}
        self.sender = SafeMessageSender(config.max_message_length, config.message_delay)
        self.cleanup_re = re.compile(r"#+\s|\*\*")
        self.link_deletus_re = re.compile(r"\[.+\](?=\()")
        self._register_handlers()

    def _register_handlers(self) -> None:
        @self.dp.message(CommandStart())
        async def start_handler(message: Message) -> None:
            await self._handle_start(message)

        @self.dp.message(Command("help"))
        async def help_handler(message: Message) -> None:
            await self._handle_help(message)

        @self.dp.message(Command("clean_history"))
        async def clean_handler(message: Message) -> None:
            await self._handle_clean_history(message)

        @self.dp.message(Command(commands=["status", "stasut"]))
        async def status_handler(message: Message) -> None:
            await self._handle_status(message)

        @self.dp.message(Command("status_local"))
        async def status_local_handler(message: Message) -> None:
            await self._handle_status_local(message)

        @self.dp.message(Command("finish_test"))
        async def finish_handler(message: Message) -> None:
            await self._handle_finish_test_command(message)

        @self.dp.message()
        async def message_handler(message: Message) -> None:
            await self._handle_message(message)

        @self.dp.callback_query()
        async def callback_handler(callback_query: CallbackQuery) -> None:
            await self._handle_callback(callback_query)

    @staticmethod
    def _request_parameters(message: Message, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if message.from_user:
            name = (message.from_user.full_name or message.from_user.first_name or "").strip()
            if name:
                result["user_display_name"] = name
        if extra:
            result.update(extra)
        return result

    @staticmethod
    def _state_to_emoji(state: Optional[str]) -> str:
        return STATE_EMOJI.get((state or "").strip().lower(), "❓")

    def _get_or_create_session(self, user_id: int) -> UserSession:
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = UserSession()
        return self.user_sessions[user_id]

    def _set_dialog_state(self, user_id: int, state: Optional[str]) -> None:
        if state:
            self._get_or_create_session(user_id).dialog_state = str(state)

    async def _resolve_user_state(self, user_id: int) -> str:
        cached = self.user_sessions.get(user_id)
        if cached and cached.dialog_state:
            return cached.dialog_state

        async with LLMClient() as llm:
            session = await llm.get_user_session(user_id)
        state = str((session or {}).get("user_state") or "who")
        self._set_dialog_state(user_id, state)
        return state

    async def _send_text(
        self,
        message: Message,
        text: str,
        parse_mode: Optional[str] = "Markdown",
        reply_markup: Any = None,
    ) -> None:
        state = await self._resolve_user_state(message.from_user.id)
        prefix = self._state_to_emoji(state)
        await self.sender.send(
            message=message,
            text=self.sanitize_text(text),
            prefix=prefix,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    def _reply_markup_for_llm(self, resp: LLMResponse) -> Any:
        state = (resp.user_state or "").strip().lower()
        info = resp.test_info if isinstance(resp.test_info, dict) else {}
        bottoms = info.get("test_bottoms")
        if state == "test" or bottoms:
            kb = ReplyKeyboardBuilder()
            if bottoms:
                for item in bottoms:
                    kb.button(text=str(item))
            kb.row(KeyboardButton(text=FINISH_TEST_BUTTON))
            return kb.as_markup(
                resize_keyboard=True,
                one_time_keyboard=False,
                is_persistent=True,
                input_field_placeholder="Выберите вариант ответа или завершите тест",
            )
        return ReplyKeyboardRemove()

    async def _dispatch_llm_response(self, message: Message, resp: LLMResponse) -> None:
        uid = message.from_user.id
        self._set_dialog_state(uid, resp.user_state)
        sess = self._get_or_create_session(uid)
        if (resp.user_state or "").strip().lower() == "test":
            tv = getattr(resp, "test_version", None)
            sess.test_version_from_core = str(tv).strip() if tv is not None else None
        else:
            sess.test_version_from_core = None
        markup = self._reply_markup_for_llm(resp)
        if (resp.msg or "").strip():
            await self._send_text(message, resp.msg, reply_markup=markup)
        if resp.professions:
            if not (resp.msg or "").strip():
                await self._send_text(message, "\u2060", reply_markup=ReplyKeyboardRemove())
            profession_list = list(resp.professions.items())
            self._get_or_create_session(message.from_user.id).professions = profession_list
            kb = InlineKeyboardBuilder()
            for idx, (name, _) in enumerate(profession_list):
                kb.button(text=name, callback_data=f"prof:{idx}")
            kb.adjust(2)
            await self._send_text(message, PROF_LIST_TEXT, reply_markup=kb.as_markup())

    async def _show_typing_indicator(self, user_id: int) -> None:
        while True:
            try:
                await self.bot.send_chat_action(user_id, "typing")
                await asyncio.sleep(3)
            except asyncio.CancelledError:
                break
            except Exception:
                break

    def sanitize_text(self, text: str) -> str:
        cleaned = self.cleanup_re.sub("", text or "")
        cleaned = cleaned.replace("*", "-")
        cleaned = self.link_deletus_re.sub("", cleaned)
        return cleaned

    async def _handle_start(self, message: Message) -> None:
        user_id = message.from_user.id
        self.user_sessions[user_id] = UserSession(active=True, message_count=0, dialog_state="who")
        await self.bot.send_chat_action(user_id, "typing")
        await self._send_text(message, config.start_text)
        async with LLMClient() as llm:
            resp = await llm.generate_response("/start", user_id, parameters=self._request_parameters(message))
        await self._dispatch_llm_response(message, resp)

    async def _handle_help(self, message: Message) -> None:
        await self.bot.send_chat_action(message.from_user.id, "typing")
        await self._send_text(message, config.help_text)

    async def _handle_clean_history(self, message: Message) -> None:
        user_id = message.from_user.id
        await self.bot.send_chat_action(user_id, "typing")
        async with LLMClient() as llm:
            text = await llm.clean_user_history(user_id)
        session = self._get_or_create_session(user_id)
        session.dialog_state = "who"
        session.test_version_from_core = None
        await self._send_text(message, text, reply_markup=ReplyKeyboardRemove())

    async def _handle_status(self, message: Message) -> None:
        user_id = message.from_user.id
        await self.bot.send_chat_action(user_id, "typing")
        async with LLMClient() as llm:
            payload = await llm.get_user_session(user_id)
        if not payload:
            await self._send_text(message, "Не удалось получить статус. Попробуйте повторить чуть позже.")
            return

        state = payload.get("user_state") or "who"
        self._set_dialog_state(user_id, state)
        status_text = (
            "Текущий статус диалога:\n\n"
            f"- Фаза: `{state}`\n"
            f"- Тип пользователя: `{payload.get('user_type') or 'не определен'}`\n"
            f"- Сообщений в истории: `{len(payload.get('conversation_history') or [])}`\n"
            f"- Поля метаданных: `{', '.join(sorted((payload.get('user_metadata') or {}).keys())) or 'нет'}`\n"
            f"- Локальная сессия в боте: `{'да' if user_id in self.user_sessions else 'нет'}`"
        )
        await self._send_text(message, status_text)

    async def _handle_status_local(self, message: Message) -> None:
        user_id = message.from_user.id
        await self.bot.send_chat_action(user_id, "typing")
        had_local_session = user_id in self.user_sessions
        restore_attempted = False
        restore_success = False
        if user_id not in self.user_sessions:
            restore_attempted = True
            restore_success = await self._restore_session_from_db(user_id)
        session = self.user_sessions.get(user_id)
        if not session:
            await self._send_text(message, "Локальная сессия отсутствует в памяти бота для этого пользователя.")
            return

        async with LLMClient() as llm:
            crud = await llm.get_user_session(user_id)
        meta = (crud or {}).get("user_metadata") or {}
        ts = meta.get("test_session")
        ts_line = "нет"
        if isinstance(ts, dict):
            ts_line = f"index=`{ts.get('current_index')}`, ответов=`{len(ts.get('answers') or [])}`"
        state_source = "memory" if had_local_session else ("crud_restored" if restore_success else "none")
        local_status = (
            "Локальный статус в TelegramBot:\n\n"
            f"- state_source: `{state_source}`\n"
            f"- restore_attempted_now: `{restore_attempted}`\n"
            f"- restore_success_now: `{restore_success}`\n"
            f"- active: `{session.active}`\n"
            f"- message_count: `{session.message_count}`\n"
            f"- professions в сессии: `{bool(session.professions)}`\n"
            f"- dialog_state (кэш из графа): `{session.dialog_state}`\n"
            f"- test_version (кэш из ответа core, при фазе test): `{session.test_version_from_core or 'нет'}`\n"
            f"- test_session (из CRUD): `{ts_line}`"
        )
        await self._send_text(message, local_status)

    async def _handle_finish_test_command(self, message: Message) -> None:
        user_id = message.from_user.id
        await self.bot.send_chat_action(user_id, "typing")
        async with LLMClient() as llm:
            resp = await llm.finish_test_early(user_id, parameters=self._request_parameters(message))
        await self._dispatch_llm_response(message, resp)

    async def _restore_session_from_db(self, user_id: int) -> bool:
        async with LLMClient() as llm:
            payload = await llm.get_user_session(user_id)
        if not payload:
            return False

        user_state = payload.get("user_state") or "who"
        metadata = payload.get("user_metadata") or {}
        history = payload.get("conversation_history") or []
        has_db = (
            payload.get("app_user_id") is not None
            or bool(history)
            or bool(metadata)
            or bool(payload.get("user_type"))
            or user_state != "who"
        )
        if not has_db:
            return False

        session = self._get_or_create_session(user_id)
        session.active = True
        session.message_count = 0
        session.dialog_state = str(user_state)
        return True

    async def _handle_message(self, message: Message) -> None:
        user_id = message.from_user.id
        text = message.text or ""

        if user_id not in self.user_sessions:
            restored = await self._restore_session_from_db(user_id)
            if not restored:
                await self._send_text(message, "Пожалуйста, начните с команды /start")
                return

        session = self._get_or_create_session(user_id)
        if not session.active:
            await self._send_text(message, "Пожалуйста, начните с команды /start")
            return

        session = self._get_or_create_session(user_id)

        if text == FINISH_TEST_BUTTON:
            await self.bot.send_chat_action(user_id, "typing")
            async with LLMClient() as llm:
                resp = await llm.finish_test_early(user_id, parameters=self._request_parameters(message))
            await self._dispatch_llm_response(message, resp)
            return

        session.message_count += 1
        typing_task = asyncio.create_task(self._show_typing_indicator(user_id))
        try:
            async with LLMClient() as llm:
                resp = await llm.generate_response(
                    text,
                    user_id,
                    parameters=self._request_parameters(message),
                )
            await self._dispatch_llm_response(message, resp)
        except Exception:
            logger.exception("Ошибка при генерации ответа")
            await self._send_text(message, "Извините, произошла ошибка при обработке вашего сообщения.")
        finally:
            typing_task.cancel()

    async def _handle_callback(self, callback_query: CallbackQuery) -> None:
        await callback_query.answer()
        user_id = callback_query.from_user.id
        data = callback_query.data or ""

        if data == "back_to_professions":
            await self._show_professions_list(callback_query)
            return

        if not callback_query.message:
            return

        try:
            index = int(data.replace("prof:", "").replace("road:", ""))
        except ValueError:
            await self._send_text(callback_query.message, "❌ Ошибка при обработке выбора профессии.")
            return

        professions = self._get_or_create_session(user_id).professions
        if not (0 <= index < len(professions)):
            await self._send_text(callback_query.message, "❌ Профессия не найдена. Попробуйте еще раз.")
            return

        profession_name, _ = professions[index]
        if data.startswith("prof:"):
            await self._show_profession_details(callback_query, profession_name, index)
        elif data.startswith("road:"):
            await self._show_profession_roadmap(callback_query, profession_name)
        else:
            await self._send_text(callback_query.message, "❌ Ошибка при обработке выбора профессии.")

    async def _show_profession_details(self, callback_query: CallbackQuery, profession_name: str, index: int) -> None:
        if not callback_query.message:
            return
        typing_task = asyncio.create_task(self._show_typing_indicator(callback_query.from_user.id))
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 Назад к списку профессий", callback_data="back_to_professions")
        kb.button(text="📈 Показать роудмап", callback_data=f"road:{index}")
        kb.adjust(1)
        try:
            async with LLMClient() as llm:
                resp = await llm.get_profession_info(profession_name, callback_query.from_user.id)
            await self._send_text(callback_query.message, resp.msg, reply_markup=kb.as_markup())
        except Exception:
            logger.exception("Ошибка при получении описания профессии %s", profession_name)
            await self._send_text(
                callback_query.message,
                f"📋 **{profession_name}**\n\nИзвините, не удалось получить подробное описание этой профессии.",
                reply_markup=kb.as_markup(),
            )
        finally:
            typing_task.cancel()

    async def _show_profession_roadmap(self, callback_query: CallbackQuery, profession_name: str) -> None:
        if not callback_query.message:
            return
        typing_task = asyncio.create_task(self._show_typing_indicator(callback_query.from_user.id))
        kb = InlineKeyboardBuilder()
        kb.button(text="🔙 Назад к списку профессий", callback_data="back_to_professions")
        kb.adjust(1)
        try:
            async with LLMClient() as llm:
                resp = await llm.get_profession_roadmap(profession_name, callback_query.from_user.id)
            await self._send_text(callback_query.message, resp.msg, reply_markup=kb.as_markup())
        except Exception:
            logger.exception("Ошибка при получении roadmap профессии %s", profession_name)
            await self._send_text(
                callback_query.message,
                f"📋 **{profession_name}**\n\nИзвините, не удалось получить подробное описание этой профессии.",
                reply_markup=kb.as_markup(),
            )
        finally:
            typing_task.cancel()

    async def _show_professions_list(self, callback_query: CallbackQuery) -> None:
        if not callback_query.message:
            return
        session = self._get_or_create_session(callback_query.from_user.id)
        if not session.professions:
            await self._send_text(
                callback_query.message,
                "❌ Список профессий не найден. Попробуйте начать новый диалог с помощью команды /start",
            )
            return

        kb = InlineKeyboardBuilder()
        for idx, (name, _) in enumerate(session.professions):
            kb.button(text=name, callback_data=f"prof:{idx}")
        kb.adjust(2)

        state = await self._resolve_user_state(callback_query.from_user.id)
        prefixed = f"{self._state_to_emoji(state)} {PROF_LIST_TEXT}"
        try:
            await callback_query.message.edit_text(prefixed, parse_mode="Markdown", reply_markup=kb.as_markup())
        except TelegramBadRequest:
            await self._send_text(callback_query.message, PROF_LIST_TEXT, reply_markup=kb.as_markup())

    async def start_polling(self) -> None:
        logger.info("Запуск бота...")
        await self.dp.start_polling(self.bot)

    async def stop(self) -> None:
        logger.info("Остановка бота...")
        await self.bot.session.close()


async def main() -> None:
    bot = TelegramBot()
    try:
        await bot.start_polling()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
