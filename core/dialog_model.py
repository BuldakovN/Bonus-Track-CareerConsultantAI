"""
Оркестрация диалога (логика перенесена из model/start_llm.py).
LLM и БД — только через HTTP (llm-service, crud-service).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import yaml
from dotenv import load_dotenv

from common.rag_client import rag_search

load_dotenv()

folder_id = os.getenv("YANDEX_CLOUD_FOLDER", "")
api_key = os.getenv("YANDEX_CLOUD_API_KEY", "")
web_search_api_url = os.getenv("WEB_SEARCH_API_URL", "http://localhost:1000")

_core_dir = Path(__file__).resolve().parent
_repo_root = _core_dir.parent
_model_dir = _repo_root / "model"
if (_core_dir / "config.yaml").exists():
    _config_dir = Path(os.getenv("CORE_CONFIG_DIR", str(_core_dir)))
else:
    _config_dir = Path(os.getenv("CORE_CONFIG_DIR", str(_model_dir)))
config_path = _config_dir / "config.yaml"
prof_tests_path = _config_dir / "prof_tests.yaml"


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=yaml.FullLoader)


config = load_yaml(config_path)
prof_tests = load_yaml(prof_tests_path)


def _canonical_prof_test_key(raw: Optional[str]) -> str:
    """Имя теста от LLM → ключ в prof_tests.yaml (синонимы из старых промптов/enum)."""
    if not isinstance(raw, str):
        return ""
    name = raw.strip()
    keys = (prof_tests.get("test_questions") or {}).keys()
    if name in keys:
        return name
    aliases = {
        "Якоря карьеры Шейна": "Тест Якоря карьеры Шейна",
        "Тест Холланда (RIASEC)": "Тест Холланда/RIASEC",
        "MBTI": "Тест MBTI",
        "PCM": "Тест PCM",
    }
    mapped = aliases.get(name)
    if mapped and mapped in keys:
        return mapped
    return name


EDUCATION_JSON = Path(
    os.getenv("EDUCATION_JSON_PATH", str(_repo_root / "data" / "education" / "education_detailed.json"))
)


class UserState:
    WHO = "who"
    ABOUT = "about"
    TEST = "test"
    RECOMMENDATION = "recommendation"
    TALK = "talk"
    # Кратковременная фиксация в БД при блокировке prompt-injection (граф → persist)
    INJECT_ATTEMPT = "inject_attempt"


class UserType:
    SCHOOL = "school"
    STUDENT = "student"
    WORKER = "worker"


PROF_CONTEXT_DICT: Dict[str, Dict[str, Any]] = {}


class DialogModel:
    def __init__(self) -> None:
        self._crud_base = os.getenv("CRUD_SERVICE_URL", "http://localhost:8010").rstrip("/")
        self._llm_base = os.getenv("LLM_SERVICE_URL", "http://localhost:8001").rstrip("/")
        self.conversation_history: Dict[str, List[Dict[str, str]]] = {}
        self.user_state: Dict[str, str] = {}
        self.user_type: Dict[str, Optional[str]] = {}
        self.user_metadata: Dict[str, Dict[str, Any]] = {}
        # Пустое значение → v2 (кнопки, test_session, /finish_test_early); v1 только явно: test_run_version=v1
        self.test_variant = (os.getenv("test_run_version") or "v2").strip()
        self.user_last_seen: Dict[str, datetime] = {}
        self._web_search = None

    def _web_search_client(self):
        if self._web_search is None:
            from core.web_search_travily import WebSearch

            self._web_search = WebSearch(api_key="asd", api_base_url=web_search_api_url)
        return self._web_search

    async def _hydrate_from_crud(self, user_id: str) -> None:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.get(f"{self._crud_base}/users/{user_id}/session")
            r.raise_for_status()
            data = r.json()
        self.conversation_history[user_id] = list(data.get("conversation_history") or [])
        self.user_state[user_id] = data.get("user_state") or UserState.WHO
        self.user_type[user_id] = data.get("user_type")
        self.user_metadata[user_id] = dict(data.get("user_metadata") or {})

    async def persist(self, user_id: str) -> None:
        payload = {
            "user_state": self.user_state.get(user_id, UserState.WHO),
            "user_type": self.user_type.get(user_id),
            "user_metadata": self.user_metadata.get(user_id, {}),
            "conversation_history": self.conversation_history.get(user_id, []),
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.put(f"{self._crud_base}/users/{user_id}/session", json=payload)
            r.raise_for_status()

    async def clean_user_history(self, user_id: str) -> None:
        self.conversation_history.pop(user_id, None)
        self.user_state.pop(user_id, None)
        self.user_type.pop(user_id, None)
        self.user_metadata.pop(user_id, None)
        self.user_last_seen.pop(user_id, None)
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.delete(f"{self._crud_base}/users/{user_id}")
            r.raise_for_status()

    def get_user_info(self, user_id: str) -> dict:
        return {
            user_id: {
                "user_state": self.user_state.get(user_id),
                "user_type": self.user_type.get(user_id),
                "user_metadata": self.user_metadata.get(user_id),
            }
        }

    async def add_system_message(self, content: str, user_id: str) -> None:
        self.conversation_history[user_id].append({"role": "system", "text": content})

    async def add_human_message(self, content: str, user_id: str) -> None:
        self.conversation_history[user_id].append({"role": "user", "text": content})

    async def add_ai_message(self, content: str, user_id: str) -> None:
        self.conversation_history[user_id].append({"role": "assistant", "text": content})

    async def _llm_chat_messages(self, messages: List[Dict[str, str]]) -> Tuple[str, int]:
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.post(f"{self._llm_base}/v1/chat", json={"messages": messages})
            r.raise_for_status()
            data = r.json()
        return data["text"], int(data.get("tokens") or 0)

    async def extract_user_type(self, user_id: str) -> Optional[str]:
        who_user = self.user_metadata[user_id]["who_user"]
        user_type = await self.toll_run(who_user, tool_name="tools")
        ut = user_type["user_type"]
        if ut == UserType.SCHOOL:
            return UserType.SCHOOL
        if ut == UserType.STUDENT:
            return UserType.STUDENT
        if ut == UserType.WORKER:
            return UserType.WORKER
        return None

    async def summarization(self, user_id: str) -> str:
        story = ""
        for i in self.conversation_history[user_id]:
            if i["role"] == "system":
                continue
            story += f"{i['role']}: {i['text']}\n\n"

        prompt = config["summarization"]
        messages = [{"role": "system", "text": prompt}, {"role": "user", "text": story}]
        res, _llm_tokens = await self._llm_chat_messages(messages)
        return res

    async def update_user_state(self, ai_response: str, user_id: str) -> bool:
        current_state = self.user_state[user_id]
        pattern = r"\[EXIT]"
        match = re.search(pattern, ai_response, re.IGNORECASE)
        if match:
            if current_state == UserState.WHO and self.user_type[user_id] is None:
                user_story = await self.summarization(user_id)
                self.user_metadata[user_id] = {"who_user": user_story}
                self.user_state[user_id] = UserState.ABOUT
                self.user_type[user_id] = await self.extract_user_type(user_id)
                return True

            if current_state == UserState.ABOUT:
                user_story = await self.summarization(user_id)
                self.user_metadata[user_id]["about_user"] = user_story
                self.user_state[user_id] = UserState.TEST
                return True

            if current_state == UserState.TEST:
                self.user_metadata[user_id]["test_user"] = ai_response
                if self.test_variant == "v1":
                    user_story = await self.summarization(user_id)
                    self.user_metadata[user_id]["test_user"] = user_story
                self.user_state[user_id] = UserState.RECOMMENDATION
                return True

            if current_state == UserState.TALK:
                return True

        return False

    async def toll_run(self, message: str, tool_name: str) -> Any:
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.post(
                f"{self._llm_base}/v1/tool_call",
                json={
                    "message": message,
                    "tool_key": tool_name,
                    "temperature": 0.6,
                    "max_tokens": 2000,
                },
            )
            r.raise_for_status()
            data = r.json()
        return data["result"]

    async def chat_loop(self, user_id: str, user_input: Optional[str] = None) -> str:
        if user_input is not None:
            await self.add_human_message(user_input, user_id)
        messages = self.conversation_history[user_id]
        ai_response, _tokens = await self._llm_chat_messages(messages)
        ai_response = await self.check_response(ai_response)
        await self.add_ai_message(ai_response, user_id)
        return ai_response

    @staticmethod
    async def check_response(ai_response: str) -> str:
        return ai_response.split("Пользователь:")[0]

    async def start_talk(self, user_input: str, user_id: str, parameters: Optional[dict] = None) -> Any:
        parameters = parameters or {}
        self.user_last_seen[user_id] = datetime.now()
        await self._hydrate_from_crud(user_id)

        dn = parameters.get("user_display_name")
        if dn:
            self.user_metadata.setdefault(user_id, {})
            name = str(dn).strip()[:256]
            if name:
                self.user_metadata[user_id]["user_display_name"] = name

        if parameters.get("finish_test_early"):
            if self.user_state[user_id] != UserState.TEST:
                return "Сейчас тест не активен."
            if self.test_variant != "v2":
                return "Досрочное завершение поддерживается только для пошагового теста (v2)."

        if self.user_state[user_id] == UserState.WHO:
            if not self.conversation_history.get(user_id):
                system_prompt = config["who_are_you_prompt"]
                await self.add_system_message(system_prompt, user_id)
            ai_response = await self.chat_loop(user_id, user_input)
            new_state = await self.update_user_state(ai_response, user_id)
            if not new_state:
                return ai_response
            self.conversation_history[user_id] = []
            user_input = None

        if self.user_state[user_id] == UserState.ABOUT:
            if not self.conversation_history.get(user_id):
                user_type = self.user_type[user_id]
                if user_type == UserType.SCHOOL:
                    system_prompt = config["about_school_prompt"]
                elif user_type == UserType.STUDENT:
                    system_prompt = config["about_student_prompt"]
                else:
                    system_prompt = config["about_worker_prompt"]
                system_prompt = system_prompt.replace("<user_metadata>", self.user_metadata[user_id]["who_user"])
                await self.add_system_message(system_prompt, user_id)

            ai_response = await self.chat_loop(user_id, user_input)
            new_state = await self.update_user_state(ai_response, user_id)
            if not new_state:
                return ai_response
            self.conversation_history[user_id] = []

        if self.user_state[user_id] == UserState.TEST:
            if self.test_variant == "v2":
                if not self.user_metadata[user_id].get("test_for_user"):
                    return await self.recommend_test_v2(user_id)

                out = await self._handle_test_v2_turn(user_id, user_input, parameters)
                if out is not None:
                    return out
                # Переход TEST → RECOMMENDATION выполнен внутри _handle_test_v2_turn
            else:
                if not self.conversation_history.get(user_id):
                    await self.recommend_test(user_id)
                    system_prompt = config["test_run_prompt"]
                    user_metadata = (
                        f"{self.user_metadata[user_id]['who_user']}\n{self.user_metadata[user_id]['about_user']}"
                    )
                    test = self.user_metadata[user_id]["recommended_test"]
                    system_prompt = system_prompt.replace("<user_metadata>", user_metadata)
                    system_prompt = system_prompt.replace("<test>", test)
                    await self.add_system_message(system_prompt, user_id)
                    user_input = "/start"

                ai_response = await self.chat_loop(user_id, user_input)
                new_state = await self.update_user_state(ai_response, user_id)
                if not new_state:
                    return ai_response
                self.conversation_history[user_id] = []
                return

        if self.user_state[user_id] == UserState.RECOMMENDATION:
            system_prompt = config["recommend_profession_prompt"]
            await self.add_system_message(system_prompt, user_id)
            keys_with_info = ["who_user", "about_user", "test_user"]
            parts = []
            for key in keys_with_info:
                if self.user_metadata[user_id].get(key) is not None:
                    parts.append(self.user_metadata[user_id][key])
            u_in = "\n".join(parts)
            u_in = f"\n\nИнформация о пользователе:\n{u_in}"
            ai_response = await self.chat_loop(user_id, u_in)
            self.user_metadata[user_id]["ai_recommendation"] = ai_response
            self.user_metadata[user_id]["ai_recommendation_json"] = await self.toll_run(
                ai_response, tool_name="make_json_tool"
            )
            self.user_state[user_id] = UserState.TALK
            self.conversation_history[user_id] = []
            return ai_response

        if self.user_state[user_id] == UserState.TALK:
            system_prompt = config["talk_prompt"]
            system_prompt = system_prompt.replace("<who_user>", self.user_metadata[user_id]["who_user"])
            system_prompt = system_prompt.replace("<about_user>", self.user_metadata[user_id]["about_user"])
            system_prompt = system_prompt.replace("<test_user>", self.user_metadata[user_id]["test_user"])
            if self.user_metadata[user_id].get("ai_recommendation_json"):
                system_prompt = system_prompt.replace(
                    "<ai_recommendation_json>",
                    str(self.user_metadata[user_id]["ai_recommendation_json"]["professions"]),
                )
            else:
                system_prompt = system_prompt.replace("# РЕКОМЕНДОВАННЫЕ ПРОФЕССИИ:", "")
            if len(self.conversation_history[user_id]) == 0:
                await self.add_system_message(system_prompt, user_id)
            self.conversation_history[user_id].insert(0, {"role": "system", "text": system_prompt})
            ai_response = await self.chat_loop(user_id, user_input)
            new_recommendation = await self.toll_run(ai_response, tool_name="is_recommendation_tool")
            if new_recommendation and new_recommendation.get("new_recommendation"):
                self.user_metadata[user_id]["ai_recommendation"] = ai_response
                self.user_metadata[user_id]["ai_recommendation_json"] = await self.toll_run(
                    ai_response, tool_name="make_json_tool"
                )
            return ai_response

        return None

    async def go_rag(self, profession_name: str, user_id: str) -> str:
        profession_full = self.user_metadata[user_id]["ai_recommendation_json"]["professions"][profession_name]
        profession_full = f"{profession_name}\n{profession_full}"
        prof_info = await rag_search(query=profession_full, k=2, api_key=api_key, folder_id=folder_id)
        about_profession = ""
        for doc in prof_info:
            about_profession += f"{doc[0].page_content}\n\n"

        profession = config["is_docs_about_profession_prompt"]
        profession = profession.replace("<text1>", profession_full)
        profession = profession.replace("<text2>", about_profession)

        is_context = None

        if profession_name in PROF_CONTEXT_DICT:
            profession_desc = PROF_CONTEXT_DICT[profession_name].get("description")
            if profession_desc:
                await self.add_ai_message(profession_desc, user_id)
                return profession_desc
            is_context = PROF_CONTEXT_DICT[profession_name].get("is_context")
        else:
            PROF_CONTEXT_DICT[profession_name] = {}

        if is_context is None:
            docs_about_profession = await self.toll_run(message=profession, tool_name="is_docs_about_profession_tool")
            is_context = docs_about_profession["is_context"] if docs_about_profession else False
            PROF_CONTEXT_DICT[profession_name]["is_context"] = is_context

        if is_context:
            system_promt = config["describe_profession_prompt"]
            system_promt = system_promt.replace("<about_professions>", profession)
        else:
            system_promt = config["describe_profession_with_no_context_prompt"]

        system_promt = system_promt.replace("<profession>", profession_name)
        messages = [{"role": "system", "text": system_promt}]
        profession_desc, _t = await self._llm_chat_messages(messages)
        PROF_CONTEXT_DICT[profession_name]["description"] = profession_desc
        await self.add_ai_message(profession_desc, user_id)
        return profession_desc

    async def go_rag_roadmap(self, profession_name: str, user_id: str) -> str:
        profession_desc = PROF_CONTEXT_DICT[profession_name]["description"]
        courses = await rag_search(
            query=profession_desc, k=15, api_key=api_key, folder_id=folder_id, index_dir="COURSES_DIR"
        )
        about_courses = ""
        with open(EDUCATION_JSON, encoding="utf-8") as f:
            links_data = f.read()
            links = json.loads(links_data)

        for doc in courses:
            about_courses += f"{doc[0].page_content}\n"
            link_name = doc[0].metadata["key"]
            link_data = links.get(link_name, None)
            if link_data:
                about_courses += f"Ссылка: {links[link_name]['link']}\n"
            about_courses += 80 * "_"
            about_courses += "\n\n"

        courses_match = f"{profession_name}\n{about_courses}"
        is_context = False
        docs_about_courses = await self.toll_run(message=courses_match, tool_name="is_docs_about_courses_tool")
        if PROF_CONTEXT_DICT.get(profession_name):
            is_context = docs_about_courses["is_context"]

        courses_prompt = config["create_roadmap_prompt"]

        if not is_context:
            system = (
                f"Сформируй поисковой запрос, по которому в интернете можно найти курсы для указанной"
                f"профессии. Верни только поисковой запрос"
            )
            profession_full = self.user_metadata[user_id]["ai_recommendation_json"]["professions"][profession_name]
            messages = [{"role": "system", "text": system}, {"role": "user", "text": f"{profession_full}"}]
            courses_from_web, _tok = await self._llm_chat_messages(messages)
            try:
                about_courses = await self._web_search_client().create_course_info(
                    query=courses_from_web, max_results=3
                )
                courses_prompt = courses_prompt.replace("<about_courses>", about_courses)
            except Exception:
                courses_prompt = config["create_roadmap_no_context_prompt"]

        courses_prompt = courses_prompt.replace("<about_profession>", profession_desc)
        courses_prompt = courses_prompt.replace("<profession>", profession_name)
        courses_prompt = courses_prompt.replace("<who_user>", self.user_metadata[user_id]["who_user"])
        courses_prompt = courses_prompt.replace("<about_user>", self.user_metadata[user_id]["about_user"])

        messages = [{"role": "system", "text": courses_prompt}]
        roadmap, _t = await self._llm_chat_messages(messages)
        await self.add_ai_message(roadmap, user_id)
        return roadmap

    async def recommend_test(self, user_id: str) -> None:
        recommendation_prompt = config["test_recommendation_prompt"]
        await self.add_system_message(recommendation_prompt, user_id)
        user_input = "\n".join(str(v) for v in self.user_metadata[user_id].values())
        ai_response = await self.chat_loop(user_id, user_input)
        self.user_metadata[user_id]["recommended_test"] = ai_response
        self.conversation_history[user_id] = []

    def _prof_test_description(self, test_for_user: str) -> str:
        desc_map = config.get("prof_tests_description") or {}
        if isinstance(desc_map, dict) and test_for_user in desc_map:
            return str(desc_map[test_for_user])
        return str((prof_tests.get("test_description") or {}).get(test_for_user, ""))

    async def _finalize_test_v2_to_recommendation(self, user_id: str, collected: List) -> None:
        """Суммаризация ответов, сброс test_session, переход в recommendation (один запуск start_talk)."""
        meta = self.user_metadata[user_id]
        test_for_user = meta.get("test_for_user")
        if not test_for_user:
            meta.pop("test_session", None)
            self.user_state[user_id] = UserState.RECOMMENDATION
            self.conversation_history[user_id] = []
            return

        test_description = self._prof_test_description(test_for_user)
        rules = str((prof_tests.get("test_description") or {}).get(test_for_user, ""))

        if len(collected) > 2:
            user_answers = await self.convert_to_qa_format(collected)
            system_prompt = (
                f"Перед тобой результаты тестирования пользователя. Был проведен {test_for_user}\n\n"
                f"ОПИСАНИЕ ТЕСТА:\n{test_description}\n\nПроанализируй ответы пользователя."
                f"Сделай суммаризацию информации, выдели ключевые аспекты"
            )
            user_prompt = f"ПРАВИЛА ПРОХОЖДЕНИЯ ТЕСТА:\n{rules}\n\nТЕСТИРОВАНИЕ ПОЛЬЗОВАТЕЛЯ:\n{user_answers}"
            await self.add_system_message(system_prompt, user_id)
            ai_response = await self.chat_loop(user_id, user_prompt)
            meta["test_user"] = ai_response
        elif len(collected) > 0:
            meta["test_user"] = await self.convert_to_qa_format(collected)
        else:
            meta["test_user"] = "Тест завершён досрочно: ответы на вопросы не были получены."

        meta.pop("test_session", None)
        self.user_state[user_id] = UserState.RECOMMENDATION
        self.conversation_history[user_id] = []

    async def _handle_test_v2_turn(self, user_id: str, user_input: str, parameters: Dict[str, Any]) -> Optional[str]:
        """
        Вся логика пошагового теста v2 в модели (состояние в user_metadata.test_session).
        Возвращает текст пользователю или None, если выполнен переход в RECOMMENDATION.
        """
        meta = self.user_metadata[user_id]
        rt = meta.get("recommended_test") or {}
        questions: List[str] = list(rt.get("test_questions") or [])
        bottoms: List[str] = list(rt.get("test_bottoms") or [])

        tr_legacy = parameters.get("test_results")
        if tr_legacy:
            pairs = [list(x) for x in tr_legacy]
            meta["test_session"] = {"current_index": len(questions), "answers": pairs}
            await self._finalize_test_v2_to_recommendation(user_id, pairs)
            return None

        if parameters.get("finish_test_early"):
            ts = meta.get("test_session") or {"current_index": 0, "answers": []}
            collected = list(ts.get("answers") or [])
            await self._finalize_test_v2_to_recommendation(user_id, collected)
            return None

        ts = meta.get("test_session")
        if ts is None:
            ts = {"current_index": 0, "answers": []}
            meta["test_session"] = ts

        idx = int(ts.get("current_index") or 0)
        answers: List = list(ts.get("answers") or [])
        ts["answers"] = answers

        prompt = (user_input or "").strip()
        finish_markers = ("🚫 Завершить тест", "/finish_test")
        if prompt in finish_markers:
            await self._finalize_test_v2_to_recommendation(user_id, answers)
            return None

        if not questions:
            return "Не удалось загрузить вопросы теста. Попробуйте позже."

        if idx >= len(questions):
            await self._finalize_test_v2_to_recommendation(user_id, answers)
            return None

        if idx == 0 and len(answers) == 0 and not prompt:
            td = rt.get("test_description") or self._prof_test_description(meta["test_for_user"])
            return (
                "Спасибо за ответы! Сейчас я проведу небольшой тест, чтобы на его основе подобрать профессии\n\n"
                f"{td}\n\n{questions[0]}"
            )

        if not prompt:
            return questions[idx]

        if prompt not in bottoms:
            return (
                "Пожалуйста, выберите один из предложенных вариантов ответа.\n\n"
                f"{questions[idx]}"
            )

        answers.append([questions[idx], prompt])
        idx += 1
        ts["current_index"] = idx
        ts["answers"] = answers

        if idx >= len(questions):
            await self._finalize_test_v2_to_recommendation(user_id, answers)
            return None

        return questions[idx]

    async def recommend_test_v2(self, user_id: str) -> str:
        about_user = "\n".join(str(v) for v in self.user_metadata[user_id].values())
        select_test_message = config["prof_test_description_for_tool"]
        select_test_message = select_test_message.replace("<about_user>", about_user)
        tool_out = await self.toll_run(message=select_test_message, tool_name="select_test_tool")
        raw_name = tool_out["user_test"] if isinstance(tool_out, dict) else ""
        test_for_user = _canonical_prof_test_key(raw_name)
        if test_for_user not in (prof_tests.get("test_questions") or {}):
            return (
                "Не удалось сопоставить выбранный тест с каталогом методик. "
                "Попробуйте отправить сообщение ещё раз или начните с /start."
            )
        self.user_metadata[user_id]["test_for_user"] = test_for_user

        test_description = prof_tests["test_description"][test_for_user]
        test_questions = prof_tests["test_questions"][test_for_user]
        test_bottoms = prof_tests["test_bottoms"][test_for_user]
        self.user_metadata[user_id]["recommended_test"] = {
            "test_description": test_description,
            "test_questions": test_questions,
            "test_bottoms": test_bottoms,
        }
        self.user_metadata[user_id]["test_session"] = {"current_index": 0, "answers": []}
        td = self._prof_test_description(test_for_user)
        if not test_questions:
            return "Не удалось подобрать вопросы для теста. Попробуйте позже."
        q0 = test_questions[0]
        return (
            "Спасибо за ответы! Сейчас я проведу небольшой тест, чтобы на его основе подобрать профессии\n\n"
            f"{td}\n\n{q0}"
        )

    @staticmethod
    async def convert_to_qa_format(data_list: List) -> str:
        result_lines = []
        for _i, item in enumerate(data_list, 1):
            question = item[0]
            answer = item[1]
            result_lines.append(f"Вопрос: {question}")
            result_lines.append(f"Ответ пользователя: {answer}")
            result_lines.append("")
        return "\n".join(result_lines)
