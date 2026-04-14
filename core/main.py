"""
Core API: оркестрация для Telegram и других клиентов.
"""
import logging
import os
from datetime import datetime

import httpx
from fastapi import FastAPI, Header
from pydantic import BaseModel
from typing import Any, Dict, Optional

from prometheus_fastapi_instrumentator import Instrumentator

from common.error_logging import setup_service_error_logging
from core.dialog_model import DialogModel
from core.graph_workflow import build_turn_graph

_log_level = getattr(logging, (os.getenv("CORE_LOG_LEVEL", "INFO").upper()), logging.INFO)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=_log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
logging.getLogger("core").setLevel(_log_level)
setup_service_error_logging("core")

app = FastAPI(title="Core Service", version="0.1.0")
Instrumentator().instrument(app).expose(app)

_dialog = DialogModel()
_turn_graph = build_turn_graph(_dialog)


def _coerce_turn_out_to_llm_fields(out: dict) -> dict:
    """Граф/langgraph может отдать не-строки; LLM также иногда кладёт в professions не-str значения."""
    msg = out.get("response_msg")
    if msg is None:
        msg = ""
    elif not isinstance(msg, str):
        msg = str(msg)

    prof = out.get("professions")
    if prof is not None and not isinstance(prof, dict):
        prof = None

    ti = out.get("test_info")
    if ti is not None and not isinstance(ti, dict):
        ti = None

    us = out.get("user_state")
    if us is not None and not isinstance(us, str):
        us = str(us)

    tv = out.get("test_version")
    if tv is not None and not isinstance(tv, str):
        tv = str(tv).strip() or None

    return {
        "msg": msg,
        "professions": prof,
        "test_info": ti,
        "user_state": us,
        "test_version": tv,
    }


class LLMResponse(BaseModel):
    msg: str
    professions: Optional[Dict[str, Any]] = None
    test_info: Optional[Dict[str, Any]] = None
    user_state: Optional[str] = None
    # test_run_version (v1/v2), только если user_state == test
    test_version: Optional[str] = None


class Context(BaseModel):
    user_id: str
    prompt: str = ""
    parameters: dict = {}


class ProfessionRequest(BaseModel):
    user_id: str
    profession_name: str


class Message(BaseModel):
    user_id: str
    msg: str
    timestamp: str


class RebuildFAISSPartResult(BaseModel):
    ok: bool
    error: Optional[str] = None


class RebuildFAISSResponse(BaseModel):
    professions: RebuildFAISSPartResult
    courses: RebuildFAISSPartResult


class RebuildCoursesFAISSResponse(BaseModel):
    courses: RebuildFAISSPartResult


def _vector_store_url() -> str:
    return (os.getenv("VECTOR_STORE_SERVICE_URL") or "http://localhost:8030").rstrip("/")


@app.post("/v1/admin/rebuild-courses-faiss-indexes", response_model=RebuildCoursesFAISSResponse)
async def rebuild_courses_faiss_indexes(authorization: Optional[str] = Header(None)) -> RebuildCoursesFAISSResponse:
    """
    Прокси к микросервису vector_store: пересборка FAISS только для курсов
    (эмбеддер и каталоги — в окружении vector_store, см. ``vector_store/app/store_paths.py``).
    """
    base = _vector_store_url()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
            r = await client.post(f"{base}/v1/admin/rebuild-courses-faiss-indexes")
            r.raise_for_status()
            data = r.json()
        courses = data.get("courses") or {}
        return RebuildCoursesFAISSResponse(
            courses=RebuildFAISSPartResult(ok=bool(courses.get("ok", True)), error=courses.get("error"))
        )
    except Exception as e:
        logging.getLogger("core").exception("rebuild courses FAISS proxy failed")
        return RebuildCoursesFAISSResponse(courses=RebuildFAISSPartResult(ok=False, error=str(e)))


@app.post("/v1/admin/rebuild-faiss-indexes", response_model=RebuildFAISSResponse)
async def rebuild_faiss_indexes(authorization: Optional[str] = Header(None)) -> RebuildFAISSResponse:
    """
    Прокси к микросервису vector_store: пересборка FAISS для профессий и курсов.

    Каталоги по умолчанию: ``data/profession/profession_vector/<slug>/`` и
    ``data/education/education_vector/<slug>/`` на стороне vector_store.

    Включение (опционально): ``CORE_REBUILD_FAISS_SECRET`` и заголовок ``Authorization: Bearer <secret>``.
    """

    # secret = (os.getenv("CORE_REBUILD_FAISS_SECRET") or "").strip()
    # if not secret:
    #     raise HTTPException(
    #         status_code=503,
    #         detail="Endpoint disabled: set CORE_REBUILD_FAISS_SECRET",
    #     )
    # if (authorization or "").strip() != f"Bearer {secret}":
    #     raise HTTPException(status_code=401, detail="Unauthorized")

    base = _vector_store_url()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
            r = await client.post(f"{base}/v1/admin/rebuild-faiss-indexes")
            r.raise_for_status()
            data = r.json()
        prof = data.get("professions") or {}
        courses = data.get("courses") or {}
        return RebuildFAISSResponse(
            professions=RebuildFAISSPartResult(ok=bool(prof.get("ok", True)), error=prof.get("error")),
            courses=RebuildFAISSPartResult(ok=bool(courses.get("ok", True)), error=courses.get("error")),
        )
    except Exception as e:
        logging.getLogger("core").exception("rebuild FAISS proxy failed")
        err = RebuildFAISSPartResult(ok=False, error=str(e))
        return RebuildFAISSResponse(professions=err, courses=err)


@app.get("/")
def read_root():
    return {"message": "Welcome to Core API"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/dialog/turn", response_model=LLMResponse)
async def dialog_turn(context: Context) -> LLMResponse:
    out = await _turn_graph.ainvoke(
        {
            "user_id": context.user_id,
            "prompt": context.prompt,
            "parameters": context.parameters,
        }
    )
    fields = _coerce_turn_out_to_llm_fields(out if isinstance(out, dict) else {})
    return LLMResponse(**fields)


@app.post("/v1/dialog/clean", response_model=LLMResponse)
async def dialog_clean(context: Context) -> LLMResponse:
    await _dialog.clean_user_history(context.user_id)
    return LLMResponse(
        msg=f"История общения и все метаданные о пользователе {context.user_id} удалены",
        professions=None,
        test_info=None,
        user_state=None,
        test_version=None,
    )


@app.post("/v1/dialog/test/finish_early", response_model=LLMResponse)
async def dialog_test_finish_early(context: Context) -> LLMResponse:
    """Досрочное завершение теста: граф сам переводит фазу и при необходимости формирует рекомендации."""
    merged = {**(context.parameters or {}), "finish_test_early": True}
    return await dialog_turn(Context(user_id=context.user_id, prompt=context.prompt or "", parameters=merged))


@app.post("/v1/profession/info", response_model=LLMResponse)
async def profession_info(request: ProfessionRequest) -> LLMResponse:
    await _dialog._hydrate_from_crud(request.user_id)
    response = await _dialog.go_rag(profession_name=request.profession_name, user_id=request.user_id)
    user_metadata = _dialog.user_metadata.get(request.user_id, {})
    ai_recommendation_json = user_metadata.get("ai_recommendation_json")
    professions = ai_recommendation_json["professions"] if ai_recommendation_json else None
    await _dialog.persist(request.user_id)
    us = _dialog.user_state.get(request.user_id)
    tv = None
    if us == "test":
        tv = (_dialog.test_variant or "").strip() or None
    return LLMResponse(
        msg=response,
        professions=professions,
        user_state=us,
        test_version=tv,
    )


@app.post("/v1/profession/roadmap", response_model=LLMResponse)
async def profession_roadmap(request: ProfessionRequest) -> LLMResponse:
    await _dialog._hydrate_from_crud(request.user_id)
    response = await _dialog.go_rag_roadmap(profession_name=request.profession_name, user_id=request.user_id)
    user_metadata = _dialog.user_metadata.get(request.user_id, {})
    ai_recommendation_json = user_metadata.get("ai_recommendation_json")
    professions = ai_recommendation_json["professions"] if ai_recommendation_json else None
    await _dialog.persist(request.user_id)
    us = _dialog.user_state.get(request.user_id)
    tv = None
    if us == "test":
        tv = (_dialog.test_variant or "").strip() or None
    return LLMResponse(
        msg=response,
        professions=professions,
        user_state=us,
        test_version=tv,
    )


@app.post("/get_user_info/")
async def get_user_info(context: Context):
    await _dialog._hydrate_from_crud(context.user_id)
    response = _dialog.get_user_info(user_id=context.user_id)
    return Message(user_id=context.user_id, msg=str(response), timestamp=str(datetime.now()))


# Совместимость со старыми путями бота (опционально)
@app.post("/start_talk/", response_model=LLMResponse)
async def start_talk_compat(context: Context) -> LLMResponse:
    return await dialog_turn(context)


@app.post("/clean_history/", response_model=LLMResponse)
async def clean_history_compat(context: Context) -> LLMResponse:
    return await dialog_clean(context)


@app.post("/finish_test_early/", response_model=LLMResponse)
async def finish_test_early_compat(context: Context) -> LLMResponse:
    return await dialog_test_finish_early(context)


@app.post("/get_profession_info/", response_model=LLMResponse)
async def get_profession_info_compat(request: ProfessionRequest) -> LLMResponse:
    return await profession_info(request)


@app.post("/get_profession_roadmap/", response_model=LLMResponse)
async def get_profession_roadmap_compat(request: ProfessionRequest) -> LLMResponse:
    return await profession_roadmap(request)
