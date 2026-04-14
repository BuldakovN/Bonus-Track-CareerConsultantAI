"""
LangGraph: prepare → guard (инъекции) → dialog | persist → END.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from core.dialog_model import DialogModel, UserState
from core.injection_guard import detect_prompt_injection

logger = logging.getLogger(__name__)

INJECTION_USER_MESSAGE = (
    "Я не совсем понял ваш вопрос. Давайте вернёмся к нашему разговору: "
    "расскажите, что вас интересует в подборе профессии, или продолжите отвечать на мои вопросы."
)


class TurnState(TypedDict, total=False):
    user_id: str
    prompt: str
    parameters: Dict[str, Any]
    phase_before_inject: str
    injection_blocked: bool
    response_msg: Optional[str]
    professions: Optional[Dict[str, str]]
    test_info: Optional[Dict[str, Any]]
    user_state: Optional[str]
    test_version: Optional[str]
    error: Optional[str]


def _build_llm_view(model: DialogModel, user_id: str, raw_response: Any) -> Dict[str, Any]:
    user_metadata = model.user_metadata.get(user_id, {})
    user_state = model.user_state.get(user_id)
    ai_recommendation_json = user_metadata.get("ai_recommendation_json")
    recommended_test = user_metadata.get("recommended_test")
    professions = None
    test_info = None
    if user_state == UserState.TALK and ai_recommendation_json and ai_recommendation_json.get("professions"):
        professions = ai_recommendation_json["professions"]
    elif user_state == UserState.TEST and recommended_test and model.test_variant == "v2":
        test_info = user_metadata.get("recommended_test")
    test_version: Optional[str] = None
    if user_state == UserState.TEST:
        tv = (model.test_variant or "").strip()
        test_version = tv if tv else None
    if raw_response is None:
        msg = ""
    elif isinstance(raw_response, str):
        msg = raw_response
    else:
        msg = str(raw_response)
    return {
        "msg": msg,
        "professions": professions,
        "test_info": test_info,
        "user_state": user_state,
        "test_version": test_version,
    }


def _route_after_guard(state: TurnState) -> Literal["inject_persist", "dialog"]:
    return "inject_persist" if state.get("injection_blocked") else "dialog"


def build_turn_graph(model: DialogModel):
    async def node_prepare(state: TurnState) -> TurnState:
        uid = state["user_id"]
        await model._hydrate_from_crud(uid)
        params = state.get("parameters") or {}
        dn = params.get("user_display_name")
        if dn:
            model.user_metadata.setdefault(uid, {})
            name = str(dn).strip()[:256]
            if name:
                model.user_metadata[uid]["user_display_name"] = name
        phase = model.user_state.get(uid, UserState.WHO)
        return {**state, "phase_before_inject": phase}

    async def node_guard(state: TurnState) -> TurnState:
        prompt = state.get("prompt") or ""
        params = state.get("parameters") or {}
        if detect_prompt_injection(prompt, params):
            logger.warning(
                "prompt_injection_blocked user_id=%s phase=%s snippet=%r",
                state.get("user_id"),
                state.get("phase_before_inject"),
                prompt[:120],
            )
            return {
                **state,
                "injection_blocked": True,
                "response_msg": INJECTION_USER_MESSAGE,
                "professions": None,
                "test_info": None,
                "test_version": None,
            }
        return {**state, "injection_blocked": False}

    async def node_dialog(state: TurnState) -> TurnState:
        try:
            uid = state["user_id"]
            raw = await model.start_talk(
                state.get("prompt") or "",
                uid,
                state.get("parameters") or {},
            )
            view = _build_llm_view(model, uid, raw)
            return {
                **state,
                "response_msg": view["msg"],
                "professions": view["professions"],
                "test_info": view["test_info"],
                "user_state": view["user_state"],
                "test_version": view.get("test_version"),
            }
        except Exception as e:
            return {
                **state,
                "error": str(e),
                "response_msg": f"Ошибка: {e}",
                "professions": None,
                "test_info": None,
                "user_state": None,
                "test_version": None,
            }

    async def node_persist(state: TurnState) -> TurnState:
        if state.get("error"):
            return state
        uid = state["user_id"]
        try:
            if state.get("injection_blocked"):
                prev = state.get("phase_before_inject") or model.user_state.get(uid, UserState.WHO)
                meta = model.user_metadata.setdefault(uid, {})
                attempts = meta.setdefault("injection_attempts", [])
                if not isinstance(attempts, list):
                    attempts = []
                    meta["injection_attempts"] = attempts
                attempts.append(
                    {
                        "at": datetime.now(timezone.utc).isoformat(),
                        "phase_before": prev,
                        "prompt_snippet": (state.get("prompt") or "")[:240],
                    }
                )
                model.user_state[uid] = UserState.INJECT_ATTEMPT
                await model.persist(uid)
                model.user_state[uid] = prev
                await model.persist(uid)
            else:
                await model.persist(uid)
        except Exception as e:
            return {**state, "error": str(e)}
        return state

    g = StateGraph(TurnState)
    g.add_node("prepare", node_prepare)
    g.add_node("guard", node_guard)
    g.add_node("dialog", node_dialog)
    g.add_node("persist", node_persist)

    g.add_edge(START, "prepare")
    g.add_edge("prepare", "guard")
    g.add_conditional_edges(
        "guard",
        _route_after_guard,
        {
            "inject_persist": "persist",
            "dialog": "dialog",
        },
    )
    g.add_edge("dialog", "persist")
    g.add_edge("persist", END)
    return g.compile()
