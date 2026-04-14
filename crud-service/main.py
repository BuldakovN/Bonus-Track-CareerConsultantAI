"""
CRUD API поверх SQLite (Repository). Единственная точка доступа к БД для остальных сервисов.

Идентификация: внешний ключ (provider + external_user_id) → внутренний app_user.id.
По умолчанию путь /users/{id}/session трактуется как Telegram.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from repo.repository import DEFAULT_SQLITE_FILENAME, Repository, RepositoryConfig

app = FastAPI(title="AI-Assistant CRUD", version="0.2.0")

_db_path = os.getenv("SQLITE_PATH", f"app/db/{DEFAULT_SQLITE_FILENAME}")
Path(_db_path).parent.mkdir(parents=True, exist_ok=True)
_db_url = f"sqlite:///{_db_path}"
repo = Repository(RepositoryConfig(db_url=_db_url, echo=False))
repo.create_schema()

DEFAULT_PROVIDER = os.getenv("DEFAULT_IDENTITY_PROVIDER", "telegram")


class SessionPayload(BaseModel):
    """Снимок сессии пользователя для core."""

    user_state: str = "who"
    user_type: Optional[str] = None
    user_metadata: Dict[str, Any] = Field(default_factory=dict)
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)


class AppUserOut(BaseModel):
    app_user_id: int
    provider: str
    external_user_id: str


@app.get("/health")
def health():
    return {"status": "ok"}


def _session_response(bundle: dict) -> SessionPayload:
    if bundle.get("app_user_id") is None:
        return SessionPayload()
    return SessionPayload(
        user_state=bundle.get("user_state", "who"),
        user_type=bundle.get("user_type"),
        user_metadata=bundle.get("user_metadata") or {},
        conversation_history=bundle.get("conversation_history") or [],
    )


@app.get("/v1/identities/{provider}/{external_user_id}/session", response_model=SessionPayload)
def get_session_by_identity(provider: str, external_user_id: str):
    bundle = repo.get_session_bundle(provider, external_user_id)
    return _session_response(bundle)


@app.put("/v1/identities/{provider}/{external_user_id}/session")
def put_session_by_identity(provider: str, external_user_id: str, body: SessionPayload):
    repo.put_session_bundle(
        provider,
        external_user_id,
        body.user_state,
        body.user_type,
        dict(body.user_metadata),
        list(body.conversation_history),
    )
    return {"ok": True}


@app.delete("/v1/identities/{provider}/{external_user_id}")
def delete_session_by_identity(provider: str, external_user_id: str):
    repo.clear_identity_session(provider, external_user_id)
    return {"ok": True}


@app.delete("/v1/identities/{provider}/{external_user_id}/full")
def delete_user_completely(provider: str, external_user_id: str):
    repo.delete_identity_completely(provider, external_user_id)
    return {"ok": True}


@app.get("/v1/identities/{provider}/{external_user_id}/app-user", response_model=AppUserOut)
def resolve_app_user(provider: str, external_user_id: str):
    aid = repo.get_app_user_id(provider, external_user_id)
    if aid is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return AppUserOut(app_user_id=aid, provider=provider, external_user_id=external_user_id)


# --- Совместимость: user_id = Telegram ---


@app.get("/users/{user_id}/session", response_model=SessionPayload)
def get_session(user_id: str):
    bundle = repo.get_session_bundle(DEFAULT_PROVIDER, user_id)
    return _session_response(bundle)


@app.put("/users/{user_id}/session")
def put_session(user_id: str, body: SessionPayload):
    repo.put_session_bundle(
        DEFAULT_PROVIDER,
        user_id,
        body.user_state,
        body.user_type,
        dict(body.user_metadata),
        list(body.conversation_history),
    )
    return {"ok": True}


@app.delete("/users/{user_id}")
def delete_user(user_id: str):
    repo.clear_identity_session(DEFAULT_PROVIDER, user_id)
    return {"ok": True}
