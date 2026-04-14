import json
import re
from typing import Dict, List, Optional
from pathlib import Path
import yaml
import os
from pathlib import Path
from dotenv import load_dotenv

from common.rag_client import rag_search
from web_search_travily import WebSearch
import aiohttp
from llm_adapter import create_llm_adapter, LLMAdapter
from prometheus_client import Counter, Gauge, Histogram
import threading
import time
from datetime import datetime, timedelta

# Загружаем переменные окружения из .env файла
load_dotenv()

folder_id = os.getenv('YANDEX_CLOUD_FOLDER', '')
api_key = os.getenv('YANDEX_CLOUD_API_KEY', '')

# URL для веб-поиска (Tavily adapter)
web_search_api_url = os.getenv('WEB_SEARCH_API_URL', 'http://localhost:1000')
WebSearch = WebSearch(api_key='asd', api_base_url=web_search_api_url)

# Создаем метрики
USERS_TOTAL = Gauge('bot_users_total', 'Общее количество пользователей') # USERS_TOTAL.set(total_users)

LLM_REQUESTS = Counter('llm_requests_total', 'Всего запросов к LLM') # LLM_REQUESTS.inc()
LLM_TOKENS_RECEIVED = Counter('bot_llm_tokens_received_total', 'Всего токенов получено от LLM') # LLM_TOKENS_RECEIVED.inc(tokens_received)


LLM_REQUEST_DURATION = Histogram(
    'llm_request_duration_seconds',
    'Длительность запросов к LLM',
    buckets=[0.1, 0.3, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)


def init_yagpt_model():
    """Инициализация модели YandexGPT с авторизацией"""
    if not folder_id or not api_key:
        raise ValueError("YANDEX_CLOUD_FOLDER и YANDEX_CLOUD_API_KEY должны быть установлены в переменных окружения")


# Определяем провайдер LLM из переменных окружения (по умолчанию yandex)
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'yandex').lower()


# Определяем путь к config.yaml относительно текущего файла
config_path = Path(__file__).parent / "config.yaml"
prof_tests_path = Path(__file__).parent / "prof_tests.yaml"


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        loaded_yaml = yaml.load(f, Loader=yaml.FullLoader)
    return loaded_yaml


config = load_yaml(config_path)
prof_tests = load_yaml(prof_tests_path)


def _canonical_prof_test_key(raw: Optional[str]) -> str:
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


class UserState:
    WHO = 'who'
    ABOUT = 'about'
    TEST = 'test'
    RECOMMENDATION = 'recommendation'
    TALK = 'talk'


class UserType:
    SCHOOL = 'school'
    STUDENT = 'student'
    WORKER = 'worker'

PROF_CONTEXT_DICT = {}


class Model:
    def __init__(self, llm_provider: Optional[str] = None, **llm_kwargs):
        """
        Инициализирует модель с указанным LLM провайдером

        Args:
            llm_provider: Провайдер LLM ("yandex", "openai", "anthropic", "google", "mistral")
                         Если None, используется значение из переменной окружения LLM_PROVIDER
            **llm_kwargs: Дополнительные параметры для инициализации LLM адаптера
        """
        provider = llm_provider or LLM_PROVIDER

        # Создаем адаптер для работы с LLM
        if provider == "yandex":
            self.llm_adapter: LLMAdapter = create_llm_adapter(
                provider=provider,
                folder_id=llm_kwargs.get('folder_id') or folder_id,
                api_key=llm_kwargs.get('api_key') or api_key
            )
        else:
            self.llm_adapter: LLMAdapter = create_llm_adapter(
                provider=provider,
                **llm_kwargs
            )

        self.conversation_history: Dict[str, List[Dict]] = {}
        self.user_state: Dict[str, str] = {}
        self.user_type: Dict[str, Optional[str]] = {}
        self.user_metadata: Dict[str, Dict] = {}
        self.test_variant = (os.getenv('test_run_version') or 'v2').strip()

        self.user_last_seen = {}
        self.active_users_gauge = Gauge('bot_active_users_24h', 'Активные пользователи за последние 24 часа')
        self._start_metric_thread()

    def _start_metric_thread(self):
        """Поток для обновления метрики"""

        def update_metric():
            while True:
                try:
                    # Считаем активных за 24 часа
                    cutoff = datetime.now() - timedelta(hours=24)
                    active = sum(
                        1 for ts in self.user_last_seen.values()
                        if ts > cutoff
                    )
                    self.active_users_gauge.set(active)
                except Exception as e:
                    print(f"Metric error: {e}")
                time.sleep(60)  # Обновляем каждую минуту

        thread = threading.Thread(target=update_metric, daemon=True)
        thread.start()

    async def clean_user_history(self, user_id: str):
        self.conversation_history.pop(user_id, None)
        self.user_state.pop(user_id, None)
        self.user_type.pop(user_id, None)
        self.user_metadata.pop(user_id, None)
        USERS_TOTAL.set(len(self.conversation_history))

    async def init_user_session(self, user_id: str):
        """Инициализирует сессию пользователя только в памяти процесса."""
        if user_id not in self.conversation_history:
            self.conversation_history[user_id] = []
            self.user_state[user_id] = UserState.WHO
            self.user_type[user_id] = None
            self.user_metadata[user_id] = {}
            USERS_TOTAL.set(len(self.conversation_history))

    def get_user_info(self, user_id: str):
        return {
            user_id: {
                "user_state": self.user_state.get(user_id, None),
                "user_type": self.user_type.get(user_id, None),
                "user_metadata": self.user_metadata.get(user_id, None)
            }
        }
         
    async def add_system_message(self, content: str, user_id: str):
        self.conversation_history[user_id].append({"role": "system", "text": content})

    async def add_human_message(self, content: str, user_id: str):
        self.conversation_history[user_id].append({"role": "user", "text": content})

    async def add_ai_message(self, content: str, user_id: str):
        self.conversation_history[user_id].append({"role": "assistant", "text": content})

    async def extract_user_type(self, user_id: str) -> Optional[str]:
        """Извлекает тип пользователя из ответа модели"""
        who_user = self.user_metadata[user_id]['who_user']
        user_type = await self.toll_run(who_user, tool_name='tools')
        user_type = user_type['user_type']
        if user_type == UserType.SCHOOL:
            return UserType.SCHOOL
        elif user_type == UserType.STUDENT:
            return UserType.STUDENT
        elif user_type == UserType.WORKER:
            return UserType.WORKER
        else:
            return None

    async def summarization(self, user_id):
        story = ""
        for i in self.conversation_history[user_id]:
            if i["role"] == "system":
                continue
            story += f"{i['role']}: {i['text']}\n\n"

        prompt = config['summarization']
        messages = [{"role": "system", "text": prompt},
                    {"role": "user", "text": story}]
        with LLM_REQUEST_DURATION.time():
            res, llm_tokens = self.llm_adapter.chat_sync(messages)
        LLM_TOKENS_RECEIVED.inc(llm_tokens)
        LLM_REQUESTS.inc()
        return res

    async def update_user_state(self, ai_response: str, user_id: str):
        current_state = self.user_state[user_id]
        pattern = r'\[EXIT]'
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
                if self.test_variant == 'v1':
                    user_story = await self.summarization(user_id)
                    self.user_metadata[user_id]["test_user"] = user_story
                self.user_state[user_id] = UserState.RECOMMENDATION
                return True

            if current_state == UserState.TALK:
                return True

        return False

    async def toll_run(self, message: str, tool_name: str):
        """Выполняет tool call через LLM адаптер"""
        tools = config[tool_name]
        result, llm_tokens = self.llm_adapter.tool_call(
            message=message,
            tools=tools,
            temperature=0.6,
            max_tokens=2000
        )
        LLM_TOKENS_RECEIVED.inc(llm_tokens)
        LLM_REQUESTS.inc()
        return result

    async def chat_loop(self, user_id: str, user_input: str = None):
        # Добавляем сообщение пользователя в историю
        if user_input is not None:
            await self.add_human_message(user_input, user_id)

        # Получаем ответ модели через адаптер
        messages = self.conversation_history[user_id]
        with LLM_REQUEST_DURATION.time():
            ai_response, llm_tokens = self.llm_adapter.chat_sync(messages)
        LLM_REQUESTS.inc()
        LLM_TOKENS_RECEIVED.inc(llm_tokens)

        ai_response = await self.check_response(ai_response)
        await self.add_ai_message(ai_response, user_id)
        return ai_response

    @staticmethod
    async def check_response(ai_response):
        return ai_response.split('Пользователь:')[0]

    async def start_talk(self, user_input: str, user_id: str, parameters: dict = None):
        """Основной метод проведения диалога с пользователем"""
        self.user_last_seen[user_id] = datetime.now()
        await self.init_user_session(user_id)
        # Этап 1: Определяем, кто пользователь
        if self.user_state[user_id] == UserState.WHO:
            if not self.conversation_history.get(user_id):
                system_prompt = config['who_are_you_prompt']
                await self.add_system_message(system_prompt, user_id)
            ai_response = await self.chat_loop(user_id, user_input)
            new_state = await self.update_user_state(ai_response, user_id)
            with open('who_data.json', 'w', encoding='windows-1251') as f:
                json.dump(self.conversation_history[user_id], f, ensure_ascii=False, indent=4)

            if not new_state:
                return ai_response
            self.conversation_history[user_id] = []
            user_input = None

        # Этап 2: Узнаем пользователя ближе в зависимости от типа
        if self.user_state[user_id] == UserState.ABOUT:
            if not self.conversation_history.get(user_id):
                user_type = self.user_type[user_id]
                if user_type == UserType.SCHOOL:
                    system_prompt = config['about_school_prompt']
                elif user_type == UserType.STUDENT:
                    system_prompt = config['about_student_prompt']
                else:
                    system_prompt = config['about_worker_prompt']
                system_prompt = system_prompt.replace("<user_metadata>", self.user_metadata[user_id]['who_user'])
                await self.add_system_message(system_prompt, user_id)

            ai_response = await self.chat_loop(user_id, user_input)
            new_state = await self.update_user_state(ai_response, user_id)
            if not new_state:
                with open('about_data.json', 'w', encoding='windows-1251') as f:
                    json.dump(self.conversation_history[user_id], f, ensure_ascii=False, indent=4)
                return ai_response
            self.conversation_history[user_id] = []

        # Этап 3: Выбираем и проводим тест
        if self.user_state[user_id] == UserState.TEST:
            if self.test_variant == 'v2':
                if not self.user_metadata[user_id].get('test_for_user'):
                    _ = await self.recommend_test_v2(user_id)
                    return _

                test_for_user = self.user_metadata[user_id]['test_for_user']
                test_description = config['prof_tests_description'][test_for_user]
                if len(parameters['test_results']) > 2:
                    user_answers = await self.convert_to_qa_format(parameters['test_results'])
                    system_prompt = (f"Перед тобой результаты тестирования пользователя. Был проведен {test_for_user}\n\n"
                                     f"ОПИСАНИЕ ТЕСТА:\n{test_description}\n\nПроанализируй ответы пользователя."
                                     f"Сделай суммаризацию информации, выдели ключевые аспекты")

                    user_input = (f"ПРАВИЛА ПРОХОЖДЕНИЯ ТЕСТА:\n{prof_tests['test_description'][test_for_user]}\n\n"
                                  f"ТЕСТИРОВАНИЕ ПОЛЬЗОВАТЕЛЯ:\n{user_answers}")

                    await self.add_system_message(system_prompt, user_id)
                    ai_response = await self.chat_loop(user_id, user_input)
                    self.user_metadata[user_id]["test_user"] = ai_response

                self.user_state[user_id] = UserState.RECOMMENDATION
                self.conversation_history[user_id] = []
                return

            else:
                if not self.conversation_history.get(user_id):
                    await self.recommend_test(user_id)
                    system_prompt = config['test_run_prompt']
                    user_metadata = (f"{self.user_metadata[user_id]['who_user']}"
                                     f"\n{self.user_metadata[user_id]['about_user']}")
                    test = self.user_metadata[user_id]['recommended_test']
                    system_prompt = system_prompt.replace("<user_metadata>", user_metadata)
                    system_prompt = system_prompt.replace("<test>", test)
                    await self.add_system_message(system_prompt, user_id)
                    user_input = '/start'

                ai_response = await self.chat_loop(user_id, user_input)
                new_state = await self.update_user_state(ai_response, user_id)
                if not new_state:
                    with open('test_data.json', 'w', encoding='windows-1251') as f:
                        json.dump(self.conversation_history[user_id], f, ensure_ascii=False, indent=4)
                    return ai_response
                self.conversation_history[user_id] = []
                return

        # Этап 4: Делаем рекомендацию профессии
        if self.user_state[user_id] == UserState.RECOMMENDATION:
            system_prompt = config['recommend_profession_prompt']
            await self.add_system_message(system_prompt, user_id)
            keys_with_info = ['who_user', 'about_user', 'test_user']

            user_input = []
            for key in keys_with_info:
                if self.user_metadata[user_id].get(key) is not None:
                    user_input.append(self.user_metadata[user_id][key])
            user_input = '\n'.join(user_input)

            user_input = f"\n\nИнформация о пользователе:\n{user_input}"
            ai_response = await self.chat_loop(user_id, user_input)
            self.user_metadata[user_id]['ai_recommendation'] = ai_response
            self.user_metadata[user_id]['ai_recommendation_json'] = await self.toll_run(ai_response,
                                                                                        tool_name='make_json_tool')
            self.user_state[user_id] = UserState.TALK
            self.conversation_history[user_id] = []
            return ai_response

        if self.user_state[user_id] == UserState.TALK:
            # if not self.conversation_history.get(user_id):
            system_prompt = config['talk_prompt']
            system_prompt = system_prompt.replace("<who_user>", self.user_metadata[user_id]["who_user"])
            system_prompt = system_prompt.replace("<about_user>", self.user_metadata[user_id]["about_user"])
            system_prompt = system_prompt.replace("<test_user>", self.user_metadata[user_id]["test_user"])
            if self.user_metadata[user_id]["ai_recommendation_json"]:
                system_prompt = system_prompt.replace("<ai_recommendation_json>",
                                                      str(self.user_metadata[user_id]["ai_recommendation_json"][
                                                              "professions"]))
            else:
                system_prompt = system_prompt.replace("# РЕКОМЕНДОВАННЫЕ ПРОФЕССИИ:", "")
            if len(self.conversation_history[user_id]) == 0:
                await self.add_system_message(system_prompt, user_id)
            self.conversation_history[user_id].insert(0, {"role": "system", "text": system_prompt})
            ai_response = await self.chat_loop(user_id, user_input)
            new_recommendation = await self.toll_run(ai_response, tool_name='is_recommendation_tool')
            if new_recommendation:
                if new_recommendation['new_recommendation']:
                    self.user_metadata[user_id]['ai_recommendation'] = ai_response
                    self.user_metadata[user_id]['ai_recommendation_json'] = await self.toll_run(ai_response,
                                                                                                tool_name='make_json_tool')
            return ai_response

    async def go_rag(self, profession_name, user_id=0):
        # Подготовка описания профессии
        profession_full = self.user_metadata[user_id]["ai_recommendation_json"]["professions"][profession_name]
        profession_full = f"{profession_name}\n{profession_full}"
        prof_info = await rag_search(query=profession_full, k=2, api_key=api_key, folder_id=folder_id)
        about_profession = ''
        for doc in prof_info:
            about_profession += f"{doc[0].page_content}\n\n"

        profession = config['is_docs_about_profession_prompt']
        profession = profession.replace('<text1>', profession_full)
        profession = profession.replace('<text2>', about_profession)

        is_context = None

        if profession_name in PROF_CONTEXT_DICT:
            profession_desc = PROF_CONTEXT_DICT[profession_name].get('description')
            if profession_desc:
                await self.add_ai_message(profession_desc, user_id)
                return profession_desc
            is_context = PROF_CONTEXT_DICT[profession_name].get('is_context')
        else:
            PROF_CONTEXT_DICT[profession_name] = {}

        if is_context is None:
            docs_about_profession = await self.toll_run(message=profession, tool_name='is_docs_about_profession_tool')
            is_context = docs_about_profession['is_context'] if docs_about_profession else False
            PROF_CONTEXT_DICT[profession_name]['is_context'] = is_context
        
        if is_context:
            system_promt = config['describe_profession_prompt']
            system_promt = system_promt.replace("<about_professions>", profession)
        else:
            system_promt = config['describe_profession_with_no_context_prompt']

        system_promt = system_promt.replace("<profession>", profession_name)
        messages = [{"role": "system", "text": system_promt}]

        with LLM_REQUEST_DURATION.time():
            profession_desc, llm_tokens = self.llm_adapter.chat_sync(messages)
        LLM_REQUESTS.inc()
        LLM_TOKENS_RECEIVED.inc(llm_tokens)
        
        PROF_CONTEXT_DICT[profession_name]['description'] = profession_desc
        await self.add_ai_message(profession_desc, user_id)
        return profession_desc
    
    async def go_rag_roadmap(self, profession_name, user_id=0):
        # Подготовка описания курсов
        profession_desc = PROF_CONTEXT_DICT[profession_name]['description']
        courses = await rag_search(query=profession_desc, k=15, api_key=api_key, folder_id=folder_id,
                                   index_dir="COURSES_DIR")
        about_courses = ''
        with open('data/education/education_detailed.json', encoding='utf-8') as f:
            links_data = f.read()
            links = json.loads(links_data)

        for doc in courses:
            about_courses += f"{doc[0].page_content}\n"
            link_name = doc[0].metadata['key']
            link_data = links.get(link_name, None)
            if link_data:
                about_courses += f"Ссылка: {links[link_name]['link']}\n"
            about_courses += 80 * "_"
            about_courses += "\n\n"

        # Проверка, что найденные курсы подходят для выбранной профессии
        courses_match = f'{profession_name}\n{about_courses}'
        is_context = False
        docs_about_courses = await self.toll_run(message=courses_match, tool_name='is_docs_about_courses_tool')
        if PROF_CONTEXT_DICT[profession_name]:
            is_context = docs_about_courses['is_context']

        courses_prompt = config['create_roadmap_prompt']
        
        if not is_context:
            system = (f"Сформируй поисковой запрос, по которому в интернете можно найти курсы для указанной"
                      f"профессии. Верни только поисковой запрос")
            profession_full = self.user_metadata[user_id]["ai_recommendation_json"]["professions"][profession_name]
            messages = [{"role": "system", "text": system},
                        {"role": "user", "text": f"{profession_full}"}]
            courses_from_web, llm_tokens = self.llm_adapter.chat_sync(messages)
            LLM_REQUESTS.inc()
            LLM_TOKENS_RECEIVED.inc(llm_tokens)
            try:
                about_courses = await WebSearch.create_course_info(query=courses_from_web,
                                                                   max_results=3)
                courses_prompt = courses_prompt.replace("<about_courses>", about_courses)
            except:
                courses_prompt = config['create_roadmap_no_context_prompt']

        courses_prompt = courses_prompt.replace("<about_profession>", profession_desc)
        courses_prompt = courses_prompt.replace("<profession>", profession_name)
        courses_prompt = courses_prompt.replace("<who_user>", self.user_metadata[user_id]['who_user'])
        courses_prompt = courses_prompt.replace("<about_user>", self.user_metadata[user_id]['about_user'])

        messages = [{"role": "system", "text": courses_prompt}]
        with LLM_REQUEST_DURATION.time():
            roadmap, llm_tokens = self.llm_adapter.chat_sync(messages)
        LLM_REQUESTS.inc()
        LLM_TOKENS_RECEIVED.inc(llm_tokens)
        
        await self.add_ai_message(roadmap, user_id)
        return roadmap
    

    async def recommend_test(self, user_id: str):
        """Рекомендует тест на основе информации о пользователе"""
        recommendation_prompt = config['test_recommendation_prompt']
        await self.add_system_message(recommendation_prompt, user_id)
        user_input = "\n".join(self.user_metadata[user_id].values())
        ai_response = await self.chat_loop(user_id, user_input)

        self.user_metadata[user_id]['recommended_test'] = ai_response
        self.conversation_history[user_id] = []

    async def recommend_test_v2(self, user_id: str):
        """Рекомендует тест на основе информации о пользователе - вибираем из предоставленных"""

        about_user = "\n".join(self.user_metadata[user_id].values())
        select_test_message = config['prof_test_description_for_tool']
        select_test_message = select_test_message.replace('<about_user>', about_user)
        tool_out = await self.toll_run(message=select_test_message, tool_name='select_test_tool')
        raw_name = tool_out['user_test'] if isinstance(tool_out, dict) else ''
        test_for_user = _canonical_prof_test_key(raw_name)
        if test_for_user not in (prof_tests.get('test_questions') or {}):
            return (
                'Не удалось сопоставить выбранный тест с каталогом методик. '
                'Попробуйте отправить сообщение ещё раз или начните с /start.'
            )
        self.user_metadata[user_id]['test_for_user'] = test_for_user

        test_description = prof_tests['test_description'][test_for_user]
        test_questions = prof_tests['test_questions'][test_for_user]
        test_bottoms = prof_tests['test_bottoms'][test_for_user]
        self.user_metadata[user_id]['recommended_test'] = {'test_description': test_description,
                                                           'test_questions': test_questions,
                                                           'test_bottoms': test_bottoms, }

        return 'empty'

    @staticmethod
    async def convert_to_qa_format(data_list: List):
        """Преобразует список списков в строку формата "Вопрос: ... Ответ пользователя: ..."""
        result_lines = []

        for i, item in enumerate(data_list, 1):
            question = item[0]
            answer = item[1]
            result_lines.append(f"Вопрос: {question}")
            result_lines.append(f"Ответ пользователя: {answer}")
            result_lines.append("")  # пустая строка между блоками

        return "\n".join(result_lines)
