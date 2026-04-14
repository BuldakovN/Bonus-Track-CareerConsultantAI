"""
HTTP API для FAISS RAG: поиск и админ-пересборка индексов.
"""
from __future__ import annotations

import asyncio
import logging
import os
from functools import partial
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.search import similarity_search_hits

load_dotenv()

_log_level = getattr(logging, (os.getenv("VECTOR_STORE_LOG_LEVEL", "INFO").upper()), logging.INFO)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=_log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
logger = logging.getLogger("vector_store")

app = FastAPI(title="Vector Store (RAG)", version="0.1.0")


class SearchRequest(BaseModel):
    query: str
    k: int = 5
    index: Literal["professions", "courses"] = "professions"
    api_key: Optional[str] = None
    folder_id: Optional[str] = None
    threshold: float = Field(default=0.75, ge=0.0, le=2.0)


class SearchHit(BaseModel):
    page_content: str
    metadata: Dict[str, Any]
    score: float


class SearchResponse(BaseModel):
    hits: List[SearchHit]


class RebuildPartResult(BaseModel):
    ok: bool
    error: Optional[str] = None


class RebuildFAISSResponse(BaseModel):
    professions: RebuildPartResult
    courses: RebuildPartResult


class RebuildCoursesFAISSResponse(BaseModel):
    courses: RebuildPartResult


def _run_build_profession_faiss() -> None:
    load_dotenv()
    from app.build_profession_faiss import build_index

    build_index()


def _run_build_courses_faiss() -> None:
    load_dotenv()
    from app.build_education_faiss import build_index as build_education_index

    build_education_index()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    try:
        fn = partial(
            similarity_search_hits,
            req.query,
            req.k,
            api_key=req.api_key,
            folder_id=req.folder_id,
            index=req.index,
            threshold=req.threshold,
        )
        rows = await asyncio.to_thread(fn)
    except Exception as e:
        logger.exception("search failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    hits = [SearchHit(page_content=p, metadata=m, score=s) for p, m, s in rows]
    return SearchResponse(hits=hits)


@app.post("/v1/admin/rebuild-courses-faiss-indexes", response_model=RebuildCoursesFAISSResponse)
async def rebuild_courses_faiss_indexes() -> RebuildCoursesFAISSResponse:
    course_ok, course_err = True, None
    try:
        await asyncio.to_thread(_run_build_courses_faiss)
        logger.info("rebuild courses FAISS succeeded")
    except Exception as e:
        logger.exception("rebuild courses FAISS failed")
        course_ok, course_err = False, str(e)
    return RebuildCoursesFAISSResponse(courses=RebuildPartResult(ok=course_ok, error=course_err))


@app.post("/v1/admin/rebuild-faiss-indexes", response_model=RebuildFAISSResponse)
async def rebuild_faiss_indexes() -> RebuildFAISSResponse:
    prof_ok, prof_err = True, None
    try:
        await asyncio.to_thread(_run_build_profession_faiss)
        logger.info("rebuild professions FAISS succeeded")
    except Exception as e:
        logger.exception("rebuild professions FAISS failed")
        prof_ok, prof_err = False, str(e)

    course_ok, course_err = True, None
    try:
        await asyncio.to_thread(_run_build_courses_faiss)
        logger.info("rebuild courses FAISS succeeded")
    except Exception as e:
        logger.exception("rebuild courses FAISS failed")
        course_ok, course_err = False, str(e)

    return RebuildFAISSResponse(
        professions=RebuildPartResult(ok=prof_ok, error=prof_err),
        courses=RebuildPartResult(ok=course_ok, error=course_err),
    )


@app.get("/")
def read_root() -> dict:
    return {"message": "Vector Store (RAG) API"}
