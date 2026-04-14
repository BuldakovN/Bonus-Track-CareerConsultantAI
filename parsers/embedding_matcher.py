import os
import time
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings.yandex import YandexGPTEmbeddings


class EmbeddingProfessionMatcher:
    """Класс для сопоставления вакансий с профессиями через эмбеддинги"""
    
    def __init__(self, professions: Dict, threshold: float = 0.88):
        """
        Инициализация матчера профессий
        
        Args:
            professions: Словарь существующих профессий
            threshold: Порог схожести (0.0-1.0, где 1.0 = точное совпадение)
        """
        self.professions = professions
        self.threshold = threshold
        self.embeddings = None
        self.vector_store = None
        self._initialize_embeddings()
        self._build_profession_index()

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        try:
            import math
            dot = sum(a * b for a, b in zip(vec_a, vec_b))
            norm_a = math.sqrt(sum(a * a for a in vec_a)) or 1.0
            norm_b = math.sqrt(sum(b * b for b in vec_b)) or 1.0
            return dot / (norm_a * norm_b)
        except Exception:
            return 0.0
    
    def _initialize_embeddings(self):
        """Инициализация эмбеддингов YandexGPT"""
        load_dotenv()
        api_key = os.getenv("YANDEX_CLOUD_API_KEY")
        folder_id = os.getenv("YANDEX_CLOUD_FOLDER")
        
        if not api_key or not folder_id:
            raise ValueError(
                "Не заданы YANDEX_CLOUD_API_KEY и/или YANDEX_CLOUD_FOLDER. "
                "Укажите их в переменных окружения или в .env файле."
            )
        
        self.embeddings = YandexGPTEmbeddings(api_key=api_key, folder_id=folder_id)
        if os.getenv("VERBOSE_LOGGING", "0").lower() in ["1", "true", "yes"]:
            print("✅ Эмбеддинги YandexGPT инициализированы")
    
    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        if not text:
            return ""
        return text[:limit] + ("..." if len(text) > limit else "")

    @staticmethod
    def _skills_text(skills: List[str], amplify: int = 2) -> str:
        if not skills:
            return ""
        base = " ".join(skills)
        # Усиливаем вклад навыков повторением
        return (base + " ") * max(1, amplify)

    @staticmethod
    def _core_alias(title: str) -> str:
        import re
        t = (title or "").lower().replace("ё", "е").strip()
        # Простейшее склеивание синонимов по ключевым словам (с корректными границами слова)
        frontend_keys = ["frontend", "фронтенд", "front-end", "react", "vue", "angular"]
        qa_keys = ["qa", "тестиров", "quality assurance"]

        # Водитель: учитываем только отдельное слово или устойчивые фразы, а не подстроки в других словах
        is_driver_word = bool(re.search(r"(?<![а-яa-z])водител[а-я]*", t))
        is_driver_en = bool(re.search(r"(?<![a-z])driver(?![a-z])", t))
        has_driver_phrase = ("персональный водитель" in t) or ("личный водитель" in t) or ("офисный водитель" in t)

        for k in frontend_keys:
            if k in t:
                return "frontend разработчик"
        if is_driver_word or is_driver_en or has_driver_phrase:
            return "водитель"
        for k in qa_keys:
            if k in t:
                return "тестировщик по"
        return t
    
    @staticmethod
    def _has_driver_signals(title: str, body: str, skills: List[str]) -> bool:
        import re
        t = (title or "").lower().replace("ё", "е")
        b = (body or "").lower().replace("ё", "е")
        sk = " ".join(skills or []).lower().replace("ё", "е")
        # Сигналы водителя только как отдельные слова/фразы, чтобы не ловить "руководитель/делопроизводитель"
        word_driver = bool(re.search(r"(?<![а-яa-z])водител[а-я]*", t)) or \
                      bool(re.search(r"(?<![а-яa-z])водител[а-я]*", b)) or \
                      bool(re.search(r"(?<![а-яa-z])водител[а-я]*", sk))
        phrase_driver = any(phrase in txt for phrase in ["персональный водитель", "личный водитель", "офисный водитель"] for txt in [t, b, sk])
        en_driver = bool(re.search(r"(?<![a-z])driver(?![a-z])", t)) or \
                    bool(re.search(r"(?<![a-z])driver(?![a-z])", b)) or \
                    bool(re.search(r"(?<![a-z])driver(?![a-z])", sk))
        cat_b = any(p in txt for p in ["категории b", "категория b"] for txt in [t, b, sk])
        traffic_terms = any(p in txt for p in ["пдд", "перевозка", "пассажир", "маршрут", "автомоб", "правила дорожного движения"] for txt in [t, b, sk])
        return word_driver or phrase_driver or en_driver or cat_b or traffic_terms

    @staticmethod
    def _is_blacklisted_for_driver(title: str, body: str, skills: List[str]) -> bool:
        # Если в названии есть слово "водитель" (с границами слова) — это настоящий водитель, не блокируем
        import re
        t = (title or "").lower().replace("ё", "е")
        # Ищем слово "водител..." с границей перед словом, чтобы не ловить
        # случаи типа "руководитель" или "делопроизводитель"
        has_driver_word = bool(re.search(r"(?<![а-яa-z])водител[а-я]*", t))
        has_driver_phrase = ("персональный водитель" in t) or ("личный водитель" in t) or ("офисный водитель" in t)
        has_driver_english = "driver" in t
        if has_driver_word or has_driver_phrase or has_driver_english:
            return False
            
        # Проверяем только описание и навыки на офисные индикаторы
        b = (body or "").lower()
        sk = " ".join(skills or []).lower()
        negatives = [
            "делопроизвод", "документооборот", "руководител", "директор",
            "службы безопасности", "безопасност", "охран", "информационная безопасност",
            "кадров", "hr", "бухгалтер", "управляющ", "заместитель",
            "проект", "производств", "логистик", "филиал", "департамент"
        ]
        return any(n in b or n in sk for n in negatives)
    
    def _build_profession_index(self):
        """Создание векторного индекса профессий"""
        if not self.professions:
            print("⚠️  Нет профессий для индексации")
            return
        
        texts = []
        metadatas = []
        
        if os.getenv("VERBOSE_LOGGING", "0").lower() in ["1", "true", "yes"]:
            print(f"🔨 Создание векторного индекса для {len(self.professions)} профессий...")
        
        for prof_title, prof_data in self.professions.items():
            # Создаем полный текст профессии
            description = prof_data.get('description', '')
            skills = prof_data.get('skills', [])
            skills_text = " ".join(skills) if skills else ""
            
            # Объединяем всю информацию о профессии
            full_text = f"{prof_title} {skills_text} {description}".strip()
            
            # Ограничиваем длину текста (лимит API YandexGPT - 2048 токенов)
            if len(full_text) > 2000:
                full_text = full_text[:2000] + "..."
            
            # Пропускаем слишком короткие тексты
            if len(full_text) < 10:
                continue
                
            texts.append(full_text)
            metadatas.append({
                "title": prof_title,
                "key": prof_title,
                "original_data": prof_data
            })
        
        if not texts:
            raise RuntimeError("Нет валидных профессий для индексации")
        
        if os.getenv("VERBOSE_LOGGING", "0").lower() in ["1", "true", "yes"]:
            print(f"📝 Подготовлено {len(texts)} текстов для индексации")
            print("🔄 Создание эмбеддингов с соблюдением лимитов API...")
        
        # Создаем эмбеддинги батчами для соблюдения лимитов API
        BATCH_SIZE = 5  # 5 текстов за раз
        all_embeddings = []
        
        for i in range(0, len(texts), BATCH_SIZE):
            batch_texts = texts[i:i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE
            
            if os.getenv("VERBOSE_LOGGING", "0").lower() in ["1", "true", "yes"]:
                print(f"  📦 Обрабатываем batch {batch_num}/{total_batches} ({len(batch_texts)} текстов)")
            
            try:
                # Создаем эмбеддинги для батча
                batch_embeddings = self.embeddings.embed_documents(batch_texts)
                all_embeddings.extend(batch_embeddings)
                
                # Задержка между батчами (1.2 секунды = 12 запросов в 10 секунд)
                if i + BATCH_SIZE < len(texts):
                    time.sleep(1.2)
                    
            except Exception as e:
                print(f"❌ Ошибка при создании эмбеддингов для batch {batch_num}: {e}")
                raise
        
        # Создаем FAISS индекс из готовых эмбеддингов
        if os.getenv("VERBOSE_LOGGING", "0").lower() in ["1", "true", "yes"]:
            print("🏗️  Создание FAISS индекса...")
        pairs = [
            (texts[i], list(map(float, all_embeddings[i]))) 
            for i in range(len(texts))
        ]
        
        # Включаем normalize_L2=True, чтобы использовать косинусную близость (IndexFlatIP)
        self.vector_store = FAISS.from_embeddings(
            text_embeddings=pairs, 
            embedding=self.embeddings, 
            metadatas=metadatas,
            normalize_L2=True
        )
        
        if os.getenv("VERBOSE_LOGGING", "0").lower() in ["1", "true", "yes"]:
            print(f"✅ Векторный индекс создан для {len(texts)} профессий")
    
    def find_best_match(self, vacancy_title: str, vacancy_description: str = "", 
                       vacancy_skills: List[str] = None) -> Optional[Tuple[str, float]]:
        """
        Находит лучшую подходящую профессию для вакансии
        
        Args:
            vacancy_title: Название вакансии
            vacancy_description: Описание вакансии
            vacancy_skills: Список навыков вакансии
            
        Returns:
            Tuple[profession_title, similarity_score] или None если не найдено
            similarity_score: от 0 до 100 (чем больше, тем лучше)
        """
        if not self.vector_store:
            return None
        
        # Готовим тексты вакансии: отдельные каналы
        skills_text = " ".join(vacancy_skills) if vacancy_skills else ""
        norm_title = self._core_alias(vacancy_title)
        vacancy_title_text = norm_title
        vacancy_body_text = f"{self._truncate(vacancy_description, 1000)} {skills_text}".strip()
        
        # Ограничиваем длину каналов (защита от эксцессов)
        if len(vacancy_title_text) > 500:
            vacancy_title_text = vacancy_title_text[:500]
        if len(vacancy_body_text) > 2000:
            vacancy_body_text = vacancy_body_text[:2000] + "..."
        
        try:
            # Ищем наиболее похожие профессии (без порога, применим вручную)
            # Ищем кандидатов по исходному заголовку вакансии (короткий текст стабилизирует shortlist)
            docs = self.vector_store.similarity_search_with_score(
                vacancy_title_text,
                k=1
            )
            
            if docs:
                doc, _score = docs[0]
                profession_title = doc.metadata.get("title")
                # Собираем тексты профессии по двум каналам
                doc_data = (doc.metadata.get("original_data") or {})
                doc_skills = doc_data.get("skills", [])
                doc_desc = doc_data.get("description", "")
                doc_title_norm = self._core_alias(profession_title)
                doc_title_text = doc_title_norm
                doc_body_text = f"{self._truncate(doc_desc, 1000)} {' '.join(doc_skills)}".strip()

                # Пересчитываем косинусную схожесть по двум каналам
                try:
                    q_title_vec = self.embeddings.embed_query(vacancy_title_text)
                    q_body_vec = self.embeddings.embed_query(vacancy_body_text)
                    d_title_vec = self.embeddings.embed_query(doc_title_text)
                    d_body_vec = self.embeddings.embed_query(doc_body_text)
                    sim_title = self._cosine_similarity(q_title_vec, d_title_vec)
                    sim_body = self._cosine_similarity(q_body_vec, d_body_vec)
                    sim = (0.65 * sim_title) + (0.35 * sim_body)
                except Exception:
                    sim = -1.0

                # Доменные правила: не складывать несвязанные роли в "водитель"
                if doc_title_norm == "водитель":
                    if self._is_blacklisted_for_driver(vacancy_title, vacancy_body_text, vacancy_skills) \
                       and not self._has_driver_signals(vacancy_title, vacancy_body_text, vacancy_skills):
                        return None

                # Мягкое слияние: если почти порог и core совпал — принимаем
                if sim < self.threshold:
                    if sim >= 0.80 and doc_title_norm == norm_title:
                        similarity_percent = max(0, min(100, ((sim + 1.0) / 2.0) * 100))
                        return profession_title, similarity_percent
                    return None

                # Доменные правила: не складывать несвязанные роли в "водитель"
                if doc_title_norm == "водитель":
                    if self._is_blacklisted_for_driver(vacancy_title, vacancy_body_text, vacancy_skills) \
                       and not self._has_driver_signals(vacancy_title, vacancy_body_text, vacancy_skills):
                        return None

                similarity_percent = max(0, min(100, ((sim + 1.0) / 2.0) * 100))
                return profession_title, similarity_percent
            
        except Exception as e:
            print(f"❌ Ошибка при поиске совпадений: {e}")
        
        return None
    
    def find_top_matches(self, vacancy_title: str, vacancy_description: str = "", 
                        vacancy_skills: List[str] = None, k: int = 3) -> List[Tuple[str, float]]:
        """
        Находит топ-K наиболее подходящих профессий
        
        Args:
            vacancy_title: Название вакансии
            vacancy_description: Описание вакансии
            vacancy_skills: Список навыков вакансии
            k: Количество результатов для возврата
            
        Returns:
            List[Tuple[profession_title, similarity_score]]
        """
        if not self.vector_store:
            return []
        
        # Два канала текста вакансии
        skills_text = " ".join(vacancy_skills) if vacancy_skills else ""
        norm_title = self._core_alias(vacancy_title)
        vacancy_title_text = norm_title
        vacancy_body_text = f"{self._truncate(vacancy_description, 1000)} {skills_text}".strip()
        if len(vacancy_title_text) > 500:
            vacancy_title_text = vacancy_title_text[:500]
        if len(vacancy_body_text) > 2000:
            vacancy_body_text = vacancy_body_text[:2000] + "..."
        
        try:
            # Ищем топ-K похожих профессий (без порога, применим вручную)
            docs = self.vector_store.similarity_search_with_score(
                vacancy_title_text,
                k=k
            )
            
            results = []
            # Два канала для запроса
            skills_text = " ".join(vacancy_skills) if vacancy_skills else ""
            norm_title = self._core_alias(vacancy_title)
            vacancy_title_text = norm_title
            vacancy_body_text = f"{self._truncate(vacancy_description, 1000)} {skills_text}".strip()
            try:
                q_title_vec = self.embeddings.embed_query(vacancy_title_text)
                q_body_vec = self.embeddings.embed_query(vacancy_body_text)
            except Exception:
                q_title_vec, q_body_vec = None, None
            for doc, _score in docs:
                profession_title = doc.metadata.get("title")
                # Два канала для профессии
                doc_data = (doc.metadata.get("original_data") or {})
                doc_skills = doc_data.get("skills", [])
                doc_desc = doc_data.get("description", "")
                doc_title_norm = self._core_alias(profession_title)
                doc_title_text = doc_title_norm
                doc_body_text = f"{self._truncate(doc_desc, 1000)} {' '.join(doc_skills)}".strip()
                try:
                    if q_title_vec is None:
                        q_title_vec = self.embeddings.embed_query(vacancy_title_text)
                    if q_body_vec is None:
                        q_body_vec = self.embeddings.embed_query(vacancy_body_text)
                    d_title_vec = self.embeddings.embed_query(doc_title_text)
                    d_body_vec = self.embeddings.embed_query(doc_body_text)
                    sim_title = self._cosine_similarity(q_title_vec, d_title_vec)
                    sim_body = self._cosine_similarity(q_body_vec, d_body_vec)
                    sim = (0.65 * sim_title) + (0.35 * sim_body)
                except Exception:
                    continue

                # Доменные правила: отсекаем ложные матчи в "водитель"
                if doc_title_norm == "водитель":
                    if self._is_blacklisted_for_driver(vacancy_title, vacancy_body_text, vacancy_skills) \
                       and not self._has_driver_signals(vacancy_title, vacancy_body_text, vacancy_skills):
                        continue

                if sim >= self.threshold or (sim >= 0.80 and doc_title_norm == norm_title):
                    similarity_percent = max(0, min(100, ((sim + 1.0) / 2.0) * 100))
                    results.append((profession_title, similarity_percent))
            
            return results
            
        except Exception as e:
            print(f"❌ Ошибка при поиске топ-{k} совпадений: {e}")
            return []
    
    def add_new_profession(self, profession_title: str, profession_data: Dict):
        """
        Добавляет новую профессию в индекс (для инкрементального обновления)
        
        Args:
            profession_title: Название профессии
            profession_data: Данные профессии
        """
        if not self.vector_store:
            return
        
        # Создаем текст новой профессии
        description = profession_data.get('description', '')
        skills = profession_data.get('skills', [])
        skills_text = " ".join(skills) if skills else ""
        
        full_text = f"{profession_title} {description} {skills_text}".strip()
        
        if len(full_text) > 2000:
            full_text = full_text[:2000] + "..."
        
        if len(full_text) < 10:
            return
        
        try:
            # Создаем эмбеддинг для новой профессии
            embedding = self.embeddings.embed_query(full_text)
            # Если индекс косинусный, нормализуем вектор (||v|| = 1)
            try:
                if getattr(self.vector_store, "normalize_L2", False):
                    import math
                    norm = math.sqrt(sum(v * v for v in embedding)) or 1.0
                    embedding = [v / norm for v in embedding]
            except Exception:
                pass

            # Добавляем в векторный индекс
            self.vector_store.add_texts(
                texts=[full_text],
                embeddings=[embedding],
                metadatas=[{
                    "title": profession_title,
                    "key": profession_title,
                    "original_data": profession_data
                }]
            )
            
            if os.getenv("VERBOSE_LOGGING", "0").lower() in ["1", "true", "yes"]:
                print(f"✅ Добавлена новая профессия в индекс: {profession_title}")
            
        except Exception as e:
            print(f"❌ Ошибка при добавлении профессии {profession_title}: {e}")
    
    def get_stats(self) -> Dict:
        """Возвращает статистику по индексу"""
        if not self.vector_store:
            return {"total_professions": 0}
        
        return {
            "total_professions": len(self.professions),
            "indexed_professions": self.vector_store.index.ntotal if hasattr(self.vector_store, 'index') else 0,
            "threshold": self.threshold
        }
