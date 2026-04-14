"""
Только вызовы LLM: чат и tool_call. Конфигурация инструментов — из model/config.yaml.
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from prometheus_fastapi_instrumentator import Instrumentator

from common.error_logging import setup_service_error_logging
from model.llm_adapter import create_llm_adapter

load_dotenv()

logger = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
setup_service_error_logging("llm-service")

folder_id = os.getenv("YANDEX_CLOUD_FOLDER", "")
api_key = os.getenv("YANDEX_CLOUD_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "yandex").lower()

config_path = Path(__file__).parent / "config.yaml"


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=yaml.FullLoader)


config = _load_yaml(config_path)

if LLM_PROVIDER == "yandex":
    _adapter = create_llm_adapter(
        provider="yandex",
        folder_id=folder_id,
        api_key=api_key,
    )
else:
    _adapter = create_llm_adapter(provider=LLM_PROVIDER)

app = FastAPI(title="LLM Service", version="0.1.0")
Instrumentator().instrument(app).expose(app)


class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]


class ChatResponse(BaseModel):
    text: str
    tokens: int = 0


class ToolCallRequest(BaseModel):
    message: str
    tool_key: str = Field(..., description="Ключ набора tools в config.yaml, например tools, make_json_tool")
    temperature: float = 0.6
    max_tokens: int = 2000


class ToolCallResponse(BaseModel):
    result: Optional[Any] = None
    tokens: int = 0


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        text, tokens = _adapter.chat_sync(req.messages)
        return ChatResponse(text=text, tokens=int(tokens or 0))
    except Exception as e:
        logger.exception("Ошибка /v1/chat: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/v1/tool_call", response_model=ToolCallResponse)
def tool_call(req: ToolCallRequest):
    if req.tool_key not in config:
        raise HTTPException(status_code=400, detail=f"Unknown tool_key: {req.tool_key}")
    tools = config[req.tool_key]
    try:
        raw = _adapter.tool_call(
            message=req.message,
            tools=tools,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
    except Exception as e:
        logger.exception("Ошибка /v1/tool_call: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e

    if isinstance(raw, tuple):
        result, tokens = raw[0], raw[1] if len(raw) > 1 else 0
    else:
        result, tokens = raw, 0

    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            pass

    return ToolCallResponse(result=result, tokens=int(tokens or 0))
