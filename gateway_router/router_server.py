import contextlib
import io
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Literal, Optional

import requests
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

_ORIGINAL_PATH_READ_TEXT = Path.read_text


def _utf8_fallback_read_text(self, encoding=None, errors=None):
    try:
        return _ORIGINAL_PATH_READ_TEXT(self, encoding=encoding, errors=errors)
    except UnicodeDecodeError:
        if encoding is None:
            return _ORIGINAL_PATH_READ_TEXT(self, encoding="utf-8", errors=errors)
        raise


Path.read_text = _utf8_fallback_read_text

import router_v4
from router_v4 import (
    BACKEND_MAP,
    call_with_preset,
    call_with_orchestration,
    explain_routing,
    load_presets,
    load_profiles,
    smart_classify,
    validate_profile_config,
)


def sync_router_env() -> None:
    router_v4.LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", router_v4.LM_STUDIO_URL)
    router_v4.ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", router_v4.ANTHROPIC_API_KEY)
    router_v4.OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", router_v4.OPENAI_API_KEY)


sync_router_env()


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("router_server")

SESSION_MAX_MESSAGES = 40
DEFAULT_PROFILE = "full"


def safe_load_presets():
    with contextlib.redirect_stdout(io.StringIO()):
        return load_presets()


def safe_load_profiles():
    with contextlib.redirect_stdout(io.StringIO()):
        return load_profiles()


PRESETS = safe_load_presets()
PROFILES = safe_load_profiles()

SESSION_STORE: Dict[str, List[dict]] = {}
SESSION_LOCK = threading.Lock()


def refresh_runtime_config() -> None:
    global PRESETS, PROFILES
    PRESETS = safe_load_presets()
    PROFILES = safe_load_profiles()


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    preset: Optional[str] = None
    profile: str = DEFAULT_PROFILE
    history: List[HistoryMessage] = Field(default_factory=list)
    session_id: Optional[str] = None


app = FastAPI(title="PBL Router HTTP Service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def trim_history(history: List[dict]) -> List[dict]:
    if len(history) <= SESSION_MAX_MESSAGES:
        return history
    return history[-SESSION_MAX_MESSAGES:]


def error_response(status_code: int, message: str, detail: Optional[str] = None) -> JSONResponse:
    payload = {"error": message}
    if detail:
        payload["error_detail"] = detail
    return JSONResponse(status_code=status_code, content=payload)


def get_profile_or_error(profile_key: str):
    profile = PROFILES.get(profile_key)
    if not profile:
        return None, error_response(400, "Invalid profile", f"Profile '{profile_key}' does not exist.")
    try:
        validate_profile_config(profile_key, profile, PRESETS)
    except Exception as exc:
        return None, error_response(400, "Invalid profile config", str(exc))
    return profile, None


def get_session_history(session_id: str) -> List[dict]:
    with SESSION_LOCK:
        return list(SESSION_STORE.get(session_id, []))


def append_session_turn(session_id: str, user_message: str, assistant_message: str) -> None:
    with SESSION_LOCK:
        session_history = list(SESSION_STORE.get(session_id, []))
        session_history.extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ]
        )
        SESSION_STORE[session_id] = trim_history(session_history)


def check_lm_studio() -> bool:
    try:
        response = requests.post(
            router_v4.LM_STUDIO_URL,
            json={
                "model": router_v4.GEMMA_MODEL,
                "messages": [{"role": "user", "content": "ping"}],
                "temperature": 0,
                "max_tokens": 1,
                "stream": False,
            },
            timeout=5,
        )
        response.raise_for_status()
        return True
    except Exception:
        return False


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled exception while serving %s %s", request.method, request.url.path)
        raise

    elapsed = getattr(request.state, "elapsed_sec", round(time.perf_counter() - started, 3))
    preset_used = getattr(request.state, "preset_used", "-")
    logger.info(
        "%s %s preset=%s elapsed_sec=%.3f status=%s",
        request.method,
        request.url.path,
        preset_used,
        elapsed,
        response.status_code,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception):
    logger.exception("Unhandled application error", exc_info=exc)
    return error_response(500, "Internal server error", str(exc))


@app.get("/health")
async def health():
    sync_router_env()
    refresh_runtime_config()
    return {
        "status": "ok",
        "lm_studio_connected": check_lm_studio(),
        "claude_api_available": bool(router_v4.ANTHROPIC_API_KEY),
        "openai_api_available": bool(router_v4.OPENAI_API_KEY),
        "presets_loaded": len(PRESETS),
        "profiles_loaded": len(PROFILES),
    }


@app.get("/presets")
async def list_presets():
    refresh_runtime_config()
    presets = []
    for key, preset in PRESETS.items():
        presets.append(
            {
                "key": key,
                "name": preset.get("name", key),
                "backend": BACKEND_MAP.get(key, "local"),
                "has_json_schema": "response_format" in preset,
            }
        )
    return {"presets": presets}


@app.get("/profiles")
async def list_profiles():
    refresh_runtime_config()
    profiles = []
    for key, profile in PROFILES.items():
        profiles.append(
            {
                "key": key,
                "name": profile.get("name", key),
                "emoji": profile.get("emoji", ""),
                "active_presets": profile.get("active_presets", []),
                "default_preset": profile.get("default_preset", ""),
            }
        )
    return {"profiles": profiles}


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    with SESSION_LOCK:
        SESSION_STORE.pop(session_id, None)
    return {"status": "cleared", "session_id": session_id}


@app.post("/chat")
async def chat(payload: ChatRequest, request: Request):
    sync_router_env()
    refresh_runtime_config()

    if not PRESETS:
        return error_response(500, "No presets loaded")
    if not PROFILES:
        return error_response(500, "No profiles loaded")

    profile, profile_error = get_profile_or_error(payload.profile)
    if profile_error:
        return profile_error

    routing_debug = explain_routing(
        payload.message,
        profile.get("active_presets", []),
        profile.get("routing_priority", {}),
    )

    if payload.preset:
        if payload.preset not in PRESETS:
            return error_response(400, "Invalid preset", f"Preset '{payload.preset}' does not exist.")
        if payload.preset not in profile.get("active_presets", []):
            return error_response(
                400,
                "Preset not allowed for profile",
                f"Preset '{payload.preset}' is not active in profile '{payload.profile}'.",
            )
        preset_key = payload.preset
        classification_method = "forced"
    else:
        preset_key, classification_method = smart_classify(payload.message, profile, PRESETS)

    execution_preset = preset_key if payload.preset else router_v4.ORCHESTRATOR_EXECUTION_PRESET
    backend = BACKEND_MAP.get(execution_preset, "local")
    if backend == "claude" and not router_v4.ANTHROPIC_API_KEY:
        return error_response(400, "Missing API key", "ANTHROPIC_API_KEY is not configured.")
    if backend == "openai" and not router_v4.OPENAI_API_KEY:
        return error_response(400, "Missing API key", "OPENAI_API_KEY is not configured.")

    request_history = [item.model_dump() for item in payload.history]
    session_id = payload.session_id.strip() if payload.session_id else None
    session_history = get_session_history(session_id) if session_id else []
    combined_history = trim_history(session_history + request_history)

    if payload.preset:
        result = call_with_preset(preset_key, payload.message, PRESETS, combined_history or None)
    else:
        result = call_with_orchestration(preset_key, payload.message, PRESETS, combined_history or None)

    request.state.preset_used = result.get("execution_preset", preset_key)
    request.state.elapsed_sec = result.get("elapsed_sec", 0.0)

    if "error" in result:
        detail = result["error"]
        if backend == "local":
            return error_response(503, "LM Studio unavailable", detail)
        return error_response(500, "Router backend error", detail)

    if session_id:
        append_session_turn(session_id, payload.message, result["content"])

    response = {
        "content": result["content"],
        "preset_used": result["preset_used"],
        "preset_name": result["preset_name"],
        "backend": result["backend"],
        "execution_preset": result.get("execution_preset", preset_key),
        "execution_preset_name": result.get("execution_preset_name", result["preset_name"]),
        "orchestration_mode": result.get("orchestration_mode", "forced_direct"),
        "classification_method": classification_method,
        "elapsed_sec": result.get("elapsed_sec", 0.0),
        "usage": result.get("usage", {}),
        "routing_debug": routing_debug,
    }
    if session_id:
        response["session_id"] = session_id
    return response


if __name__ == "__main__":
    uvicorn.run(
        "router_server:app",
        host=os.environ.get("ROUTER_HOST", "0.0.0.0"),
        port=int(os.environ.get("ROUTER_PORT", "8000")),
        reload=False,
    )
