"""
Простая прослойка для вызова LLM API
"""
import aiohttp
from typing import Optional, Dict, Any
import os
import logging


logger = logging.getLogger(__name__)

# Ответы короче порога не считаем «блоком рекомендаций» для предупреждения про отсутствие кнопок.
_MIN_MSG_LEN_RECO_WITHOUT_BUTTONS = 100
_ENDPOINTS_WARN_RECO_NO_INLINE = frozenset({"dialog_turn", "finish_test_early"})


class LLMResponse:
    """Класс для представления ответа от LLM"""
    def __init__(
        self,
        msg: str,
        professions: Optional[Dict[str, Any]] = None,
        test_info: Optional[Dict] = None,
        user_state: Optional[str] = None,
        test_version: Optional[str] = None,
    ):
        self.msg = msg
        self.professions = professions or {}
        self.test_info = test_info or {}
        self.user_state = user_state
        self.test_version = test_version


def _core_button_flags(resp: LLMResponse) -> tuple[bool, bool]:
    """Reply-клавиатура теста и inline-кнопки списка профессий (как в bot2._reply_markup_for_llm / dispatch)."""
    state = (resp.user_state or "").strip().lower()
    info = resp.test_info if isinstance(resp.test_info, dict) else {}
    bottoms = info.get("test_bottoms")
    reply_keyboard = state == "test" or bool(bottoms)
    inline_professions = bool(resp.professions)
    return reply_keyboard, inline_professions


def _log_core_response(
    *,
    user_id: int,
    endpoint: str,
    http_status: int,
    resp: LLMResponse,
    warn_recommendation_without_inline: bool,
) -> None:
    state_raw = resp.user_state
    state_norm = (state_raw or "").strip().lower() or None
    reply_kb, inline_prof = _core_button_flags(resp)
    msg = resp.msg or ""
    msg_len = len(msg.strip())
    tv = getattr(resp, "test_version", None)
    logger.info(
        "core response user_id=%s endpoint=%s http_status=%s user_state=%r "
        "reply_keyboard=%s inline_profession_buttons=%s professions_count=%s msg_len=%s test_version=%r",
        user_id,
        endpoint,
        http_status,
        state_raw,
        reply_kb,
        inline_prof,
        len(resp.professions) if resp.professions else 0,
        msg_len,
        tv,
    )
    if not warn_recommendation_without_inline:
        return
    if endpoint not in _ENDPOINTS_WARN_RECO_NO_INLINE:
        return
    if state_norm != "talk":
        return
    if inline_prof:
        return
    if msg_len < _MIN_MSG_LEN_RECO_WITHOUT_BUTTONS:
        return
    logger.warning(
        "core sent a substantive talk response without inline profession buttons "
        "(expected professions dict for picker). user_id=%s endpoint=%s http_status=%s "
        "user_state=%r msg_len=%s reply_keyboard=%s",
        user_id,
        endpoint,
        http_status,
        state_raw,
        msg_len,
        reply_kb,
    )


def _log_core_request_failed(*, user_id: int, endpoint: str, http_status: int, detail: str) -> None:
    logger.info(
        "core response user_id=%s endpoint=%s http_status=%s user_state=None "
        "reply_keyboard=False inline_profession_buttons=False professions_count=0 msg_len=0 detail=%s",
        user_id,
        endpoint,
        http_status,
        detail[:500] if detail else "",
    )


class LLMClient:
    """Простая прослойка - просто вызывает API из папки model"""
    
    def __init__(self):
        # API уже запущен на localhost:8000 с токенами
        self.api_url = os.getenv('LLM_API_URL', 'http://localhost:8000/start_talk/')
        self.profession_api_url = os.getenv('LLM_PROFESSION_API_URL', 'http://localhost:8000/get_profession_info/')
        self.roadmap_api_url = os.getenv('LLM_ROADMAP_API_URL', 'http://localhost:8000/get_profession_roadmap/')
        self.clean_api_url = os.getenv('LLM_CLEAN_API_URL', 'http://localhost:8000/clean_history/')
        self.finish_test_early_url = os.getenv(
            "LLM_FINISH_TEST_URL",
            "http://localhost:8000/finish_test_early/",
        )
        self.crud_base_url = os.getenv('CRUD_SERVICE_URL', 'http://localhost:8010').rstrip('/')
        self.session: Optional[aiohttp.ClientSession] = None

    @staticmethod
    def _sanitize_service_message(msg: str) -> str:
        """
        Не показываем пользователю внутренние сообщения об ошибках сервиса.
        """
        safe_fallback = "Сервис сейчас перегружен. Пожалуйста, подождите немного и попробуйте еще раз."
        if not isinstance(msg, str):
            logger.error("LLMClient._sanitize_service_message: получено нестроковое сообщение об ошибке: %r", msg)
            print("LLMClient._sanitize_service_message: получено нестроковое сообщение об ошибке: %r", msg)
            return safe_fallback

        normalized = msg.strip()
        lowered = normalized.lower()
        # Блокируем только явные технические сообщения сервиса.
        # Нельзя фильтровать по словам "ошибка"/"error" в общем виде:
        # модель может использовать их в нормальном пользовательском ответе.
        error_markers = (
            "traceback",
            "exception:",
            "module not found",
            "internal server error",
            "bad gateway",
            "gateway timeout",
            "service unavailable",
            "connection refused",
            "timed out",
            "read timed out",
            "status code: 5",
            "http 5",
            "500 ",
            "502 ",
            "503 ",
            "504 ",
        )
        if any(marker in lowered for marker in error_markers):
            import logging
            logging.getLogger(__name__).warning(
                "LLMClient._sanitize_service_message: скрыто сообщение об ошибке от пользователя: %r", msg
            )
            print("LLMClient._sanitize_service_message: скрыто сообщение об ошибке от пользователя: %r", msg)
            return safe_fallback
        return msg
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    

    async def generate_response(self, message: str, user_id: int, parameters: dict = None) -> LLMResponse:
        """Отправляет сообщение в LLM API и возвращает ответ с профессиями"""
        if parameters is None:
            parameters = {}
        if not self.session:
            raise RuntimeError("LLMClient не инициализирован. Используйте async with.")
        
        try:
            payload = {
                "user_id": str(user_id),
                "prompt": message,
                "parameters": parameters
            }
            
           # Отправляем запрос к LLM API
            async with self.session.post(
                self.api_url,
                json=payload,
                #timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                                
                if response.status == 200:
                    result = await response.json()

                    msg = result.get("msg", "Извините, не удалось получить ответ.")
                    msg = self._sanitize_service_message(msg)
                    professions = result.get("professions") or {}
                    test_info = result.get("test_info") or {}
                    user_state = result.get("user_state")

                    resp = LLMResponse(
                        msg=msg,
                        professions=professions,
                        test_info=test_info,
                        user_state=user_state,
                        test_version=result.get("test_version"),
                    )
                    _log_core_response(
                        user_id=user_id,
                        endpoint="dialog_turn",
                        http_status=response.status,
                        resp=resp,
                        warn_recommendation_without_inline=True,
                    )
                    return resp
                else:
                    error_text = await response.text()
                    print(f"❌ Ошибка API {response.status}: {error_text}")
                    _log_core_request_failed(
                        user_id=user_id,
                        endpoint="dialog_turn",
                        http_status=response.status,
                        detail=error_text,
                    )
                    return LLMResponse(msg="Извините, произошла ошибка при обработке запроса.")

        except Exception as e:
            print(f"❌ Ошибка LLM API: {e}")
            import traceback
            traceback.print_exc()
            _log_core_request_failed(
                user_id=user_id,
                endpoint="dialog_turn",
                http_status=0,
                detail=repr(e),
            )
            return LLMResponse(msg="Извините, произошла ошибка.")

    async def finish_test_early(self, user_id: int, parameters: dict = None) -> LLMResponse:
        """Досрочное завершение теста: core переводит граф и при необходимости отдаёт рекомендации."""
        if parameters is None:
            parameters = {}
        if not self.session:
            raise RuntimeError("LLMClient не инициализирован. Используйте async with.")
        payload = {
            "user_id": str(user_id),
            "prompt": "",
            "parameters": parameters or {},
        }
        try:
            async with self.session.post(self.finish_test_early_url, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    msg = result.get("msg", "Извините, не удалось получить ответ.")
                    msg = self._sanitize_service_message(msg)
                    resp = LLMResponse(
                        msg=msg,
                        professions=result.get("professions") or {},
                        test_info=result.get("test_info") or {},
                        user_state=result.get("user_state"),
                        test_version=result.get("test_version"),
                    )
                    _log_core_response(
                        user_id=user_id,
                        endpoint="finish_test_early",
                        http_status=response.status,
                        resp=resp,
                        warn_recommendation_without_inline=True,
                    )
                    return resp
                error_text = await response.text()
                print(f"❌ Ошибка API {response.status}: {error_text}")
                _log_core_request_failed(
                    user_id=user_id,
                    endpoint="finish_test_early",
                    http_status=response.status,
                    detail=error_text,
                )
                return LLMResponse(msg="Извините, произошла ошибка при обработке запроса.")
        except Exception as e:
            print(f"❌ Ошибка finish_test_early: {e}")
            import traceback
            traceback.print_exc()
            _log_core_request_failed(
                user_id=user_id,
                endpoint="finish_test_early",
                http_status=0,
                detail=repr(e),
            )
            return LLMResponse(msg="Извините, произошла ошибка.")
    
    async def generate_start_message(self, user_id: int) -> LLMResponse:
        return await self.generate_response("/start", user_id)
    
    async def generate_help_message(self, user_id: int) -> LLMResponse:
        return await self.generate_response("/help", user_id)
    
    async def get_profession_info(self, profession_name: str, user_id: int) -> LLMResponse:
        """Получает подробную информацию о профессии через RAG систему"""
        if not self.session:
            raise RuntimeError("LLMClient не инициализирован. Используйте async with.")
        
        try:
            payload = {
                "user_id": str(user_id),
                "profession_name": profession_name,
            }
            
            async with self.session.post(
                self.profession_api_url,
                json=payload,
                #timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                
                if response.status == 200:
                    result = await response.json()
                    msg = result.get("msg", "Извините, не удалось получить информацию о профессии.")
                    msg = self._sanitize_service_message(msg)
                    resp = LLMResponse(
                        msg=msg,
                        professions=result.get("professions") or {},
                        test_info=result.get("test_info") or {},
                        user_state=result.get("user_state"),
                        test_version=result.get("test_version"),
                    )
                    _log_core_response(
                        user_id=user_id,
                        endpoint="profession_info",
                        http_status=response.status,
                        resp=resp,
                        warn_recommendation_without_inline=False,
                    )
                    return resp
                else:
                    error_text = await response.text()
                    _log_core_request_failed(
                        user_id=user_id,
                        endpoint="profession_info",
                        http_status=response.status,
                        detail=error_text,
                    )
                    return LLMResponse(msg="Извините, произошла ошибка при получении информации о профессии.")

        except Exception as e:
            print(f"Ошибка при получении информации о профессии: {e}")
            _log_core_request_failed(
                user_id=user_id,
                endpoint="profession_info",
                http_status=0,
                detail=repr(e),
            )
            return LLMResponse(msg="Извините, произошла ошибка.")

    async def get_profession_roadmap(self, profession_name: str, user_id: int) -> LLMResponse:
        """Получает подробную информацию о курсах для профессии через RAG систему"""
        if not self.session:
            raise RuntimeError("LLMClient не инициализирован. Используйте async with.")
        
        try:
            payload = {
                "user_id": str(user_id),
                "profession_name": profession_name,
            }
            
            async with self.session.post(
                self.roadmap_api_url,
                json=payload,
                #timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                
                if response.status == 200:
                    result = await response.json()
                    msg = result.get("msg", "Извините, не удалось получить информацию о профессии.")
                    msg = self._sanitize_service_message(msg)
                    resp = LLMResponse(
                        msg=msg,
                        professions=result.get("professions") or {},
                        test_info=result.get("test_info") or {},
                        user_state=result.get("user_state"),
                        test_version=result.get("test_version"),
                    )
                    _log_core_response(
                        user_id=user_id,
                        endpoint="profession_roadmap",
                        http_status=response.status,
                        resp=resp,
                        warn_recommendation_without_inline=False,
                    )
                    return resp
                else:
                    error_text = await response.text()
                    _log_core_request_failed(
                        user_id=user_id,
                        endpoint="profession_roadmap",
                        http_status=response.status,
                        detail=error_text,
                    )
                    return LLMResponse(msg="Извините, произошла ошибка при получении информации о профессии.")

        except Exception as e:
            print(f"Ошибка при получении roadmap профессии: {e}")
            _log_core_request_failed(
                user_id=user_id,
                endpoint="profession_roadmap",
                http_status=0,
                detail=repr(e),
            )
            return LLMResponse(msg="Извините, произошла ошибка.")

    async def clean_user_history(self, user_id: int):
        payload = {
            "user_id": str(user_id),
            "prompt": "prompt",
            "parameters": {}
        }

        # Отправляем запрос к LLM API
        async with self.session.post(
                self.clean_api_url,
                json=payload,
                # timeout=aiohttp.ClientTimeout(total=30)
        ) as response:

            if response.status == 200:
                logger.info(
                    "core response user_id=%s endpoint=%s http_status=%s user_state=None "
                    "reply_keyboard=False inline_profession_buttons=False professions_count=0 msg_len=0 result=clean_ok",
                    user_id,
                    "clean_history",
                    response.status,
                )
                return "Хоть сообщения и остались в чате, я забыл все, о чем мы общались."
            else:
                error_text = await response.text()
                print(f"❌ Ошибка API {response.status}: {error_text}")
                _log_core_request_failed(
                    user_id=user_id,
                    endpoint="clean_history",
                    http_status=response.status,
                    detail=error_text,
                )
                return "Извините, произошла ошибка при обработке запроса."

    async def get_user_session(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Возвращает сессию пользователя из CRUD.
        Если пользователя нет в БД, CRUD вернет сессию по умолчанию.
        """
        if not self.session:
            raise RuntimeError("LLMClient не инициализирован. Используйте async with.")

        url = f"{self.crud_base_url}/users/{user_id}/session"
        logger.info("CRUD request started: method=GET url=%s user_id=%s", url, user_id)

        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(
                        "CRUD request failed: method=GET url=%s user_id=%s status=%s body=%s",
                        url,
                        user_id,
                        response.status,
                        error_text,
                    )
                    return None
                payload = await response.json()
                logger.info(
                    "CRUD request completed: method=GET url=%s user_id=%s status=%s has_app_user_id=%s",
                    url,
                    user_id,
                    response.status,
                    payload.get("app_user_id") is not None,
                )
                return payload
        except Exception as e:
            logger.exception(
                "CRUD request exception: method=GET url=%s user_id=%s error=%s",
                url,
                user_id,
                e,
            )
            return None