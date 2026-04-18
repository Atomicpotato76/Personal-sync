"""
PBL 라우터 v4.1
==============
v4 + structured JSON 지원 + Hermes 소환 키워드
"""

import requests
import json
import time
import os
import sys
import logging
from pathlib import Path
from typing import Optional


LM_STUDIO_URL = "http://100.78.18.95:1234/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

PRESET_DIR = Path(__file__).parent / "presets"
PROFILE_DIR = Path(__file__).parent / "profiles"
STATE_FILE = Path(__file__).parent / ".router_state"
logger = logging.getLogger("router_v4")


def load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

load_env()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

GEMMA_MODEL = "gemma-4-e4b-uncensored-hauhaucs-aggressive"
CLAUDE_MODEL = "claude-sonnet-4-20250514"
GPT_MODEL = "gpt-4o"

GEMMA4_DEFAULTS = {"temperature": 1.0, "top_p": 0.95, "top_k": 64}
CONFIDENCE_THRESHOLD = 2.0
ORCHESTRATOR_EXECUTION_PRESET = "hermes"

BACKEND_MAP = {
    "hermes": "local",
    "lecture_parser": "local",
    "domain_expert": "claude",
    "critic": "openai",
    "formatter": "local",
}


def load_profiles():
    profiles = {}
    if not PROFILE_DIR.exists():
        return profiles
    for file in sorted(PROFILE_DIR.glob("*.profile.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            key = file.stem.replace(".profile", "")
            profiles[key] = data
            print(f"  {data.get('emoji', '📋')} {key:8s} │ {data.get('name', '')}")
        except Exception as e:
            print(f"  ❌ {file.name}: {e}")
    return profiles


def load_presets():
    presets = {}
    if not PRESET_DIR.exists():
        return presets
    for file in sorted(PRESET_DIR.glob("*.preset.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            key = file.stem.replace(".preset", "")
            presets[key] = data
        except Exception as e:
            print(f"  ❌ {file.name}: {e}")
    return presets


def validate_profile_config(profile_key, profile, presets):
    if not profile_key:
        raise ValueError("profile is required")
    if not isinstance(profile, dict):
        raise ValueError(f"profile '{profile_key}' is not a JSON object")

    active_presets = profile.get("active_presets")
    if not isinstance(active_presets, list) or not active_presets:
        raise ValueError(f"profile '{profile_key}' must define a non-empty active_presets list")

    missing_presets = [preset_key for preset_key in active_presets if preset_key not in presets]
    if missing_presets:
        raise ValueError(
            f"profile '{profile_key}' references unknown presets: {', '.join(sorted(missing_presets))}"
        )

    default_preset = profile.get("default_preset")
    if not default_preset:
        raise ValueError(f"profile '{profile_key}' is missing default_preset")
    if default_preset not in active_presets:
        raise ValueError(
            f"profile '{profile_key}' default_preset '{default_preset}' is not in active_presets"
        )

    return active_presets, default_preset


def validate_preset_config(preset_key, preset):
    if not preset_key:
        raise ValueError("preset is required")
    if preset is None:
        raise ValueError(f"preset '{preset_key}' does not exist")
    if not isinstance(preset, dict):
        raise ValueError(f"preset '{preset_key}' is not a JSON object")

    params = preset.get("parameters", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError(f"preset '{preset_key}' parameters must be a JSON object")

    response_format = preset.get("response_format")
    if response_format is not None:
        validate_response_format(response_format, preset_key)

    return params.copy()


def validate_response_format(response_format, preset_key=""):
    label = f"preset '{preset_key}'" if preset_key else "response_format"
    if not isinstance(response_format, dict):
        raise ValueError(f"{label} response_format must be a JSON object")

    rf_type = response_format.get("type")
    if not rf_type:
        raise ValueError(f"{label} response_format.type is required")

    if rf_type == "json_schema":
        json_schema = response_format.get("json_schema")
        if json_schema is None:
            raise ValueError(f"{label} response_format.json_schema is required")
        if isinstance(json_schema, dict):
            if not json_schema.get("name"):
                raise ValueError(f"{label} response_format.json_schema.name is required")
            schema_body = json_schema.get("schema")
            if not isinstance(schema_body, dict):
                raise ValueError(f"{label} response_format.json_schema.schema must be a JSON object")
        elif isinstance(json_schema, str):
            if not json_schema.strip():
                raise ValueError(f"{label} response_format.json_schema path/url cannot be empty")
        else:
            raise ValueError(
                f"{label} response_format.json_schema must be a file path, URL, or object"
            )


def validate_message_content(content, path):
    if isinstance(content, str):
        return
    if not isinstance(content, list):
        raise ValueError(f"{path} must be a string or an array of content parts")

    for idx, part in enumerate(content):
        part_path = f"{path}[{idx}]"
        if not isinstance(part, dict):
            raise ValueError(f"{part_path} must be a JSON object")

        if "text" in part and not isinstance(part["text"], str):
            raise ValueError(f"{part_path}.text must be a string")
        if "file" in part and not isinstance(part["file"], str):
            raise ValueError(f"{part_path}.file must be a file path string")
        if "url" in part and not isinstance(part["url"], str):
            raise ValueError(f"{part_path}.url must be a URL string")
        if "object" in part and not isinstance(part["object"], dict):
            raise ValueError(f"{part_path}.object must be a JSON object")


def validate_messages(messages):
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list")

    for idx, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"messages[{idx}] must be a JSON object")
        role = message.get("role")
        if not role:
            raise ValueError(f"messages[{idx}].role is required")
        if "content" not in message:
            raise ValueError(f"messages[{idx}].content is required")
        validate_message_content(message["content"], f"messages[{idx}].content")


def validate_payload(payload, backend, context):
    if not isinstance(payload, dict):
        raise ValueError(f"{context}: payload must be a JSON object")

    model = payload.get("model")
    if not model or not isinstance(model, str):
        raise ValueError(f"{context}: model is required")

    validate_messages(payload.get("messages"))

    response_format = payload.get("response_format")
    if response_format is not None:
        validate_response_format(response_format, context)


def summarize_payload(payload):
    def _truncate(value, limit=240):
        if isinstance(value, str) and len(value) > limit:
            return value[:limit] + "...<truncated>"
        if isinstance(value, list):
            return [_truncate(item, limit) for item in value]
        if isinstance(value, dict):
            return {k: _truncate(v, limit) for k, v in value.items()}
        return value

    return _truncate(payload)


def log_final_payload(backend, payload, context):
    logger.info(
        "Final API payload before %s call (%s): %s",
        backend,
        context,
        json.dumps(summarize_payload(payload), ensure_ascii=False),
    )


def save_state(profile_name):
    STATE_FILE.write_text(json.dumps({"last_profile": profile_name}))


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text()).get("last_profile", "full")
        except:
            pass
    return "full"


# Hermes 소환 키워드 추가!
ROUTING_RULES = {
    "lecture_parser": [
        "강의", "슬라이드", "교수님", "수업내용", "강의자료", "파싱", "추출",
    ],
    "domain_expert": [
        "시퀀싱", "assembly", "genome", "유전체", "제안서", "설계",
        "파이프라인", "PacBio", "Illumina", "ONT", "annotation",
        "gene prediction", "scaffolding", "contig", "N50",
        "coverage", "long-read", "short-read", "de novo",
    ],
    "critic": [
        "검증", "검토", "리뷰", "문제점", "타당", "교차검증",
        "verify", "validate", "review", "check", "평가", "누락", "결함",
    ],
    "formatter": [
        "PPT", "발표", "슬라이드 만들", "포맷", "보고서",
        "마크다운", "문서화", "정리해", "pptx", "프레젠테이션",
    ],
    "hermes": [
        "헤르메스", "hermes", "Hermes",
        "비서", "비서야", "비서님",
        "도와줘", "부탁해", "해줄래",
        "일정", "미팅", "이메일", "메일", "회의",
    ],
}

ROUTE_EXAMPLES = {
    "hermes": "general assistant tasks, scheduling, email drafting, request intake",
    "lecture_parser": "lecture slide analysis, concept extraction, study-note structuring",
    "domain_expert": "genomics strategy, sequencing design, assembly and annotation guidance",
    "critic": "review, validation, risk finding, flaw detection",
    "formatter": "presentation outline, document formatting, slide structure, markdown polishing",
}


def keyword_score(message, active_presets, priorities):
    msg = message.lower()
    scores = {}
    for preset_key in active_presets:
        keywords = ROUTING_RULES.get(preset_key, [])
        raw = sum(1 for kw in keywords if kw.lower() in msg)
        weight = priorities.get(preset_key, 1.0)
        scores[preset_key] = raw * weight
    return scores


def classify_with_llm(message, active_presets):
    categories_desc = {
        "hermes": "일상 업무, 일정, 이메일, 잡담, 비서 호출",
        "lecture_parser": "강의자료 분석, 키워드 추출",
        "domain_expert": "유전체학 기술 설계, 시퀀싱 전략",
        "critic": "검증, 리뷰, 결함 찾기",
        "formatter": "PPT/문서 생성",
    }
    options = "\n".join(f"- {p}: {categories_desc.get(p, '')}" for p in active_presets)
    system_prompt = f"Classify into ONE category. Output ONLY the name.\n\n{options}"

    try:
        payload = {
            "model": GEMMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "router_classification",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": active_presets,
                            }
                        },
                        "required": ["category"],
                        "additionalProperties": False,
                    },
                },
            },
            **GEMMA4_DEFAULTS,
            "max_tokens": 20,
        }
        validate_payload(payload, "local", "classifier")
        log_final_payload("local", payload, "classifier")
        resp = requests.post(LM_STUDIO_URL, json=payload, timeout=10)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        try:
            cat = json.loads(content).get("category", "").strip().lower()
        except Exception:
            cat = content.lower()
        for p in active_presets:
            if p in cat:
                return p
        return active_presets[0]
    except:
        return None


def smart_classify(message, profile, presets):
    active, default = validate_profile_config(profile.get("name", "unknown"), profile, presets)
    priorities = profile.get("routing_priority", {})

    if len(active) == 1:
        return active[0], "profile(single)"

    scores = keyword_score(message, active, priorities)
    ranked = sorted(
        [(k, v) for k, v in scores.items() if v > 0],
        key=lambda x: x[1], reverse=True,
    )

    if ranked:
        first_k, first_s = ranked[0]
        second_s = ranked[1][1] if len(ranked) > 1 else 0
        if first_s >= 1 and (second_s == 0 or first_s / max(second_s, 0.01) >= CONFIDENCE_THRESHOLD):
            return first_k, "keyword"

    llm = classify_with_llm(message, active)
    if llm and llm in active:
        return llm, "llm"

    return default, "default"


def explain_routing(message, active_presets, priorities):
    scores = keyword_score(message, active_presets, priorities)
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return {
        "scores": scores,
        "ranked": [
            {"preset": preset_key, "score": score}
            for preset_key, score in ranked
        ],
    }


def build_orchestration_system_prompt(target_preset_key, presets):
    hermes_preset = presets.get(ORCHESTRATOR_EXECUTION_PRESET, {})
    target_preset = presets.get(target_preset_key, {})
    hermes_prompt = hermes_preset.get("systemPrompt", "").strip()
    target_prompt = target_preset.get("systemPrompt", "").strip()
    target_name = target_preset.get("name", target_preset_key)
    target_summary = ROUTE_EXAMPLES.get(target_preset_key, target_preset_key)

    orchestration_block = (
        "Orchestration mode is active.\n"
        f"You are still Hermes, but for this request you must operate in the '{target_preset_key}' lane.\n"
        f"Selected specialist role: {target_name}\n"
        f"Role intent: {target_summary}\n\n"
        "Execution rules:\n"
        "- Keep the Hermes voice and structured output contract.\n"
        "- Apply the selected specialist's reasoning style before answering.\n"
        "- Do not mention internal routing, preset names, or orchestration unless asked.\n"
        "- If the specialist role expects analysis, perform that analysis and then package the result as Hermes.\n"
        "- Prefer direct, ready-to-use outputs.\n"
    )

    if target_prompt:
        orchestration_block += f"\nSpecialist instructions to follow:\n{target_prompt}\n"

    if hermes_prompt:
        return f"{hermes_prompt}\n\n{orchestration_block}"
    return orchestration_block


def call_with_orchestration(target_preset_key, user_message, presets, history=None):
    hermes_preset = presets.get(ORCHESTRATOR_EXECUTION_PRESET)
    target_preset = presets.get(target_preset_key)

    if hermes_preset is None:
        return {"error": f"orchestrator execution preset '{ORCHESTRATOR_EXECUTION_PRESET}' does not exist"}
    if target_preset is None:
        return {"error": f"target preset '{target_preset_key}' does not exist"}

    try:
        params = validate_preset_config(ORCHESTRATOR_EXECUTION_PRESET, hermes_preset)
        if "response_format" in hermes_preset:
            params["response_format"] = hermes_preset["response_format"]
    except Exception as e:
        return {"error": str(e)}

    backend = BACKEND_MAP.get(ORCHESTRATOR_EXECUTION_PRESET)
    if not backend:
        return {"error": f"unknown backend mapping for preset '{ORCHESTRATOR_EXECUTION_PRESET}'"}

    system_prompt = build_orchestration_system_prompt(target_preset_key, presets)

    try:
        result = BACKEND_DISPATCH[backend](
            system_prompt,
            user_message,
            params,
            history,
        )
        result["preset_used"] = target_preset_key
        result["preset_name"] = target_preset.get("name", "")
        result["execution_preset"] = ORCHESTRATOR_EXECUTION_PRESET
        result["execution_preset_name"] = hermes_preset.get("name", "")
        result["execution_backend"] = backend
        result["orchestration_mode"] = "hermes_wrapped" if target_preset_key != ORCHESTRATOR_EXECUTION_PRESET else "direct_hermes"
        return result
    except requests.exceptions.ConnectionError:
        return {"error": f"{backend} 연결 실패"}
    except Exception as e:
        return {"error": f"{backend}: {str(e)}"}


def call_local(system_prompt, user_message, params, history=None):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": params.get("model", GEMMA_MODEL),
        "messages": messages,
        "temperature": params.get("temperature", GEMMA4_DEFAULTS["temperature"]),
        "top_p": params.get("top_p", GEMMA4_DEFAULTS["top_p"]),
        "max_tokens": params.get("max_tokens", 4096),
        "stream": False,
    }
    if "response_format" in params:
        payload["response_format"] = params["response_format"]

    t0 = time.time()
    validate_payload(payload, "local", "call_local")
    log_final_payload("local", payload, "call_local")
    resp = requests.post(LM_STUDIO_URL, json=payload, timeout=180)
    resp.raise_for_status()
    result = resp.json()

    return {
        "content": result["choices"][0]["message"]["content"],
        "usage": result.get("usage", {}),
        "elapsed_sec": round(time.time() - t0, 1),
        "backend": f"local ({GEMMA_MODEL})",
    }


def call_claude(system_prompt, user_message, params, history=None):
    if not ANTHROPIC_API_KEY:
        return {"error": "ANTHROPIC_API_KEY 미설정"}

    messages = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": params.get("max_tokens", 4096),
        "system": system_prompt,
        "messages": messages,
    }
    validate_messages(payload["messages"])
    log_final_payload("claude", payload, "call_claude")
    t0 = time.time()
    resp = requests.post(ANTHROPIC_URL, headers={
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }, json=payload, timeout=120)
    resp.raise_for_status()
    result = resp.json()

    return {
        "content": result["content"][0]["text"],
        "usage": result.get("usage", {}),
        "elapsed_sec": round(time.time() - t0, 1),
        "backend": f"claude ({CLAUDE_MODEL})",
    }


def call_openai(system_prompt, user_message, params, history=None):
    if not OPENAI_API_KEY:
        return {"error": "OPENAI_API_KEY 미설정"}

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": GPT_MODEL,
        "messages": messages,
        "temperature": params.get("temperature", 0.7),
        "max_tokens": params.get("max_tokens", 4096),
    }
    if "response_format" in params:
        payload["response_format"] = params["response_format"]

    t0 = time.time()
    validate_payload(payload, "openai", "call_openai")
    log_final_payload("openai", payload, "call_openai")
    resp = requests.post(OPENAI_URL, headers={
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }, json=payload, timeout=120)
    resp.raise_for_status()
    result = resp.json()

    return {
        "content": result["choices"][0]["message"]["content"],
        "usage": result.get("usage", {}),
        "elapsed_sec": round(time.time() - t0, 1),
        "backend": f"openai ({GPT_MODEL})",
    }


BACKEND_DISPATCH = {"local": call_local, "claude": call_claude, "openai": call_openai}


def call_with_preset(preset_key, user_message, presets, history=None):
    preset = presets.get(preset_key)

    try:
        params = validate_preset_config(preset_key, preset)
        if "response_format" in preset:
            params["response_format"] = preset["response_format"]
    except Exception as e:
        return {"error": str(e)}

    backend = BACKEND_MAP.get(preset_key)
    if not backend:
        return {"error": f"unknown backend mapping for preset '{preset_key}'"}
    if backend == "local":
        response_format = params.get("response_format")
        json_schema = response_format.get("json_schema") if isinstance(response_format, dict) else None
        if not isinstance(response_format, dict) or response_format.get("type") != "json_schema" or not json_schema:
            return {
                "error": (
                    f"preset '{preset_key}' uses local backend but is missing "
                    "response_format.json_schema"
                )
            }

    try:
        result = BACKEND_DISPATCH[backend](
            preset.get("systemPrompt", ""),
            user_message,
            params,
            history,
        )
        result["preset_used"] = preset_key
        result["preset_name"] = preset.get("name", "")
        return result
    except requests.exceptions.ConnectionError:
        return {"error": f"{backend} 연결 실패"}
    except Exception as e:
        return {"error": f"{backend}: {str(e)}"}


def interactive_mode(profiles, presets, initial_profile):
    current_name = initial_profile if initial_profile in profiles else "full"
    current = profiles[current_name]

    def banner():
        print(f"\n{'─' * 50}")
        print(f"{current.get('emoji', '📋')} 현재 모드: {current.get('name', '')}")
        print(f"   활성: {', '.join(current['active_presets'])}")
        print(f"   기본: {current['default_preset']}")
        print(f"{'─' * 50}\n")

    print("\n🤖 라우터 v4.1 — Profile + JSON Schema")
    print(f"   Claude: {'✅' if ANTHROPIC_API_KEY else '❌'}")
    print(f"   GPT:    {'✅' if OPENAI_API_KEY else '❌'}")
    print("   /help\n")
    banner()

    history = []
    forced = None
    debug = False

    while True:
        try:
            user_input = input(f"[{current.get('emoji', '')}] You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋"); break

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd = user_input.split(maxsplit=1)
            c = cmd[0].lower()

            if c == "/quit":
                save_state(current_name); break
            elif c == "/mode":
                if len(cmd) > 1 and cmd[1] in profiles:
                    current_name = cmd[1]
                    current = profiles[current_name]
                    history.clear()
                    forced = None
                    save_state(current_name)
                    banner()
                else:
                    for k, v in profiles.items():
                        mark = " ← 현재" if k == current_name else ""
                        print(f"  {v.get('emoji', '📋')} {k:8s} │ {v.get('name', '')}{mark}")
            elif c == "/list":
                for p in current["active_presets"]:
                    b = BACKEND_MAP.get(p, "local")
                    m = " 🔒" if p == forced else ""
                    d = " (기본)" if p == current["default_preset"] else ""
                    rf = " [JSON]" if "response_format" in presets[p] else ""
                    print(f"  {p:20s} │ {b:8s}{rf} │ {presets[p].get('name','')}{d}{m}")
            elif c == "/preset":
                if len(cmd) > 1 and cmd[1] in current["active_presets"]:
                    forced = cmd[1]; print(f"  🔒 {forced}")
                else:
                    print(f"  ❌")
            elif c == "/auto":
                forced = None; print("  🔓")
            elif c == "/debug":
                debug = not debug; print(f"  🔧 {debug}")
            elif c == "/clear":
                history.clear(); print("  🗑️")
            elif c == "/help":
                print("\n  /mode <이름> /preset <이름> /auto /list /debug /clear /quit\n")
            continue

        if forced:
            pk, method = forced, "forced"
        else:
            pk, method = smart_classify(user_input, current, presets)

        backend = BACKEND_MAP.get(pk, "local")
        has_json = "response_format" in presets.get(pk, {})
        jm = " 📋JSON" if has_json else ""
        print(f"  📌 [{method}] → {pk} [{backend}]{jm}")
        if debug:
            scores = keyword_score(user_input, current["active_presets"], current.get("routing_priority", {}))
            print(f"  🔧 {dict(sorted(scores.items(), key=lambda x: -x[1]))}")
        print("  ⏳...\n")

        result = call_with_preset(pk, user_input, presets, history)

        if "error" in result:
            print(f"  ❌ {result['error']}\n"); continue

        print(f"AI ({pk}): {result['content']}\n")
        print(f"  ⏱️  {result['elapsed_sec']}s │ {result['backend']}\n")

        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": result["content"]})
        if len(history) > 20:
            history = history[-20:]


if __name__ == "__main__":
    print("📂 로드중...\n")
    profiles = load_profiles()
    presets = load_presets()
    if not profiles or not presets:
        sys.exit(1)
    print(f"\n✅ 프로필 {len(profiles)}, 프리셋 {len(presets)}\n")

    initial = load_state()
    for i, arg in enumerate(sys.argv):
        if arg == "--mode" and i + 1 < len(sys.argv):
            initial = sys.argv[i + 1]

    interactive_mode(profiles, presets, initial)
