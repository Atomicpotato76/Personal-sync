#!/usr/bin/env python3
"""llm_router.py -- LM Studio / ChatGPT / Claude 3-tier LLM 라우팅 (v3).

구독 기반 호출 지원:
  - Claude Code CLI (`claude -p`) → Pro/Max 구독 쿼터 사용 ($0)
  - Codex CLI (`codex exec`) → ChatGPT Pro 구독 쿼터 사용 ($0)
  - API fallback → 구독 CLI 실패 시 API 키로 호출

v3.1: ModelRegistry 연동 — API에서 모델 목록 동적 조회, thinking/reasoning 지원.
v3.2: Ollama → LM Studio 전환 (OpenAI 호환 API).
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import logging
import os
import re
import shutil
import subprocess
from typing import Optional

import requests

from env_utils import get_env_value
from model_registry import ModelRegistry, ModelInfo

logger = logging.getLogger("pipeline")


class LMStudioClient:
    """LM Studio OpenAI 호환 API 클라이언트."""

    def __init__(self, config: dict):
        self.base_url = os.environ.get(
            "LMSTUDIO_BASE_URL",
            config.get("base_url", "http://localhost:1234"),
        ).rstrip("/")
        self.model = os.environ.get("LMSTUDIO_MODEL", config.get("model", ""))
        self.timeout = int(os.environ.get("LMSTUDIO_TIMEOUT", config.get("timeout", 180)))

    def is_available(self) -> bool:
        if not self.model:
            return False
        try:
            r = requests.get(f"{self.base_url}/v1/models", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def generate(self, prompt: str, system: str = "", images: list[str] | None = None) -> Optional[str]:
        model = self.model
        if not model:
            logger.warning("LM Studio 모델이 설정되지 않음 (config.yaml llm.lmstudio.model)")
            return None
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            payload: dict = {
                "model": model,
                "messages": messages,
                "stream": False,
            }
            r = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            if r.status_code == 200:
                data = r.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
                return None
            else:
                logger.error(f"LM Studio 응답 오류: {r.status_code}")
                return None
        except requests.exceptions.ConnectionError:
            logger.warning("LM Studio 서버 연결 불가 (LM Studio 실행 필요)")
            return None
        except Exception as e:
            logger.error(f"LM Studio 호출 실패: {e}")
            return None


class ExternalRouterClient:
    """External preset/profile router adapter."""

    def __init__(self, config: dict):
        self.enabled = bool(config.get("enabled", False))
        self.mode = config.get("mode", "import")
        self.project_path = (
            os.environ.get("PBL_ROUTER_DIR")
            or os.environ.get("PBL_ROUTER_PATH")
            or config.get("project_path", "")
        )
        self.server_url = os.environ.get("PBL_ROUTER_URL", config.get("server_url", "http://localhost:8000")).rstrip("/")
        self.profile = config.get("profile", "study")
        self.preset = config.get("preset", "")
        self.timeout = int(config.get("timeout", 180))
        self.task_profiles = config.get("task_profiles", {})
        self.task_presets = config.get("task_presets", {})
        self._router_module = None
        self._profiles: dict | None = None
        self._presets: dict | None = None

    def _resolve_profile(self, task_type: str) -> str:
        return self.task_profiles.get(task_type, self.profile)

    def _resolve_preset(self, task_type: str) -> str:
        return self.task_presets.get(task_type, self.preset)

    @staticmethod
    def _compose_message(prompt: str, system: str = "") -> str:
        return f"{system}\n\n{prompt}" if system else prompt

    def _load_router_module(self):
        if self._router_module is not None:
            return self._router_module
        if not self.project_path:
            logger.warning("External router project_path not configured")
            return None

        router_path = os.path.join(self.project_path, "router_v4.py")
        if not os.path.isfile(router_path):
            logger.warning(f"External router not found: {router_path}")
            return None

        try:
            from pathlib import Path

            original_read_text = Path.read_text

            def _utf8_fallback_read_text(path_obj, encoding=None, errors=None):
                try:
                    return original_read_text(path_obj, encoding=encoding, errors=errors)
                except UnicodeDecodeError:
                    if encoding is None:
                        return original_read_text(path_obj, encoding="utf-8", errors=errors)
                    raise

            spec = importlib.util.spec_from_file_location("study_pipeline_external_router_v4", router_path)
            if spec is None or spec.loader is None:
                logger.warning(f"Failed to load external router spec: {router_path}")
                return None
            module = importlib.util.module_from_spec(spec)
            Path.read_text = _utf8_fallback_read_text
            try:
                spec.loader.exec_module(module)
            finally:
                Path.read_text = original_read_text
            self._router_module = module
            return module
        except Exception as e:
            logger.warning(f"Failed to import external router: {e}")
            return None

    def _load_router_assets(self) -> bool:
        if self._profiles is not None and self._presets is not None:
            return True

        module = self._load_router_module()
        if module is None:
            return False

        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self._profiles = module.load_profiles()
                self._presets = module.load_presets()
            return True
        except Exception as e:
            logger.warning(f"Failed to load external router assets: {e}")
            return False

    def _generate_http(self, message: str, task_type: str = "") -> Optional[str]:
        profile = self._resolve_profile(task_type)
        preset = self._resolve_preset(task_type)
        payload = {"message": message, "profile": profile}
        if preset:
            payload["preset"] = preset

        try:
            response = requests.post(f"{self.server_url}/chat", json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            content = data.get("content", "").strip()
            if content:
                logger.info(
                    "External router response (http, profile=%s, preset=%s, task=%s)",
                    profile,
                    preset or "auto",
                    task_type or "general",
                )
                return content
        except Exception as e:
            logger.warning(f"External router HTTP call failed: {e}")
        return None

    def _generate_import(self, message: str, task_type: str = "") -> Optional[str]:
        if not self._load_router_assets():
            return None

        module = self._router_module
        profiles = self._profiles or {}
        presets = self._presets or {}
        if not module or not profiles or not presets:
            logger.warning("External router assets are empty")
            return None

        profile_key = self._resolve_profile(task_type)
        profile = profiles.get(profile_key) or profiles.get("study") or next(iter(profiles.values()), None)
        if profile is None:
            logger.warning("No external router profiles available")
            return None

        preset_key = self._resolve_preset(task_type)
        if preset_key:
            if preset_key not in presets:
                logger.warning(f"External router preset not found: {preset_key}")
                return None
            if preset_key not in profile.get("active_presets", []):
                logger.warning(f"Preset '{preset_key}' is not active in profile '{profile_key}'")
                return None
        else:
            preset_key, _ = module.smart_classify(message, profile, presets)

        try:
            result = module.call_with_preset(preset_key, message, presets, None)
            if "error" in result:
                logger.warning(f"External router backend error: {result['error']}")
                return None
            content = result.get("content", "").strip()
            if content:
                logger.info(
                    "External router response (import, profile=%s, preset=%s, task=%s)",
                    profile_key,
                    preset_key,
                    task_type or "general",
                )
                return content
        except Exception as e:
            logger.warning(f"External router import call failed: {e}")
        return None

    def generate(self, prompt: str, system: str = "", task_type: str = "") -> Optional[str]:
        if not self.enabled:
            return None

        message = self._compose_message(prompt, system)
        if self.mode == "http":
            return self._generate_http(message, task_type=task_type)
        return self._generate_import(message, task_type=task_type)


class ChatGPTClient:
    """OpenAI ChatGPT — Codex CLI(구독) 우선, API fallback.

    v3.1: 모델별 thinking/reasoning 자동 감지.
    """

    def __init__(self, config: dict, model_info: ModelInfo | None = None):
        self.model = config.get("model", "gpt-5.4")
        self.max_tokens = config.get("max_tokens", 4096)
        self.temperature = config.get("temperature", 0.3)
        self.prefer_subscription = config.get("prefer_subscription", True)
        self._codex_path = self._find_codex()
        # 모델 레지스트리 정보
        self._model_info = model_info
        self.thinking_enabled = model_info.thinking if model_info else False
        self.reasoning_levels = model_info.reasoning_levels if model_info else []

    def _uses_max_completion_tokens(self) -> bool:
        """gpt-5+, o-series 모델은 max_completion_tokens 파라미터를 사용."""
        m = self.model.lower()
        return bool(re.match(r"o[1-9]", m) or re.match(r"gpt-[5-9]", m))

    def _find_codex(self) -> Optional[str]:
        """Codex CLI 경로 탐색. node 경유 실행도 지원."""
        # PATH에서 찾기
        found = shutil.which("codex")
        if found:
            return found
        # npm global 설치 (node_modules 내 bin)
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            codex_js = os.path.join(appdata, "npm", "node_modules", "@openai", "codex", "bin", "codex.js")
            if os.path.isfile(codex_js):
                return codex_js  # node로 실행 필요
        # Windows 기본 설치 경로
        candidates = [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\codex\codex.exe"),
            os.path.expandvars(r"%APPDATA%\npm\codex.cmd"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return None

    def generate(
        self,
        prompt: str,
        system: str = "",
        reasoning_effort: str = "",
    ) -> Optional[str]:
        if reasoning_effort and self.reasoning_levels and reasoning_effort in self.reasoning_levels:
            result = self._call_api(prompt, system, reasoning_effort=reasoning_effort)
            if result:
                return result
            logger.warning(
                "ChatGPT reasoning 요청을 API로 처리하지 못해 기본 경로로 fallback (%s)",
                reasoning_effort,
            )

        # 1순위: Codex CLI (구독 쿼터, $0)
        if self.prefer_subscription and self._codex_path:
            result = self._call_codex(prompt, system)
            if result:
                return result
            logger.info("Codex CLI 실패 → API fallback")

        # 2순위: API
        return self._call_api(prompt, system)

    def _call_codex(self, prompt: str, system: str = "") -> Optional[str]:
        """Codex CLI로 ChatGPT Pro 구독 쿼터 사용."""
        try:
            full_prompt = f"{system}\n\n{prompt}" if system else prompt
            # .js 파일이면 node로 실행
            if self._codex_path.endswith(".js"):
                cmd = ["node", self._codex_path, "exec", full_prompt]
            else:
                cmd = [self._codex_path, "exec", full_prompt]
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, encoding="utf-8",
                timeout=120, errors="replace",
            )
            if result.returncode == 0 and result.stdout.strip():
                logger.info("ChatGPT 응답 (Codex CLI, 구독 쿼터)")
                return result.stdout.strip()
            return None
        except Exception as e:
            logger.warning(f"Codex CLI 호출 실패: {e}")
            return None

    def _call_api(self, prompt: str, system: str = "", reasoning_effort: str = "") -> Optional[str]:
        """OpenAI API로 호출 (토큰 과금).

        reasoning_effort: "low"/"medium"/"high" — thinking/pro 모델에서 추론 깊이 조절.
        """
        api_key = get_env_value("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY 환경변수 없음")
            return None
        try:
            from openai import OpenAI
        except ImportError:
            logger.error("openai 패키지 미설치: pip install openai")
            return None

        client = OpenAI(api_key=api_key, timeout=120.0)
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            token_param = "max_completion_tokens" if self._uses_max_completion_tokens() else "max_tokens"
            kwargs: dict = {
                "model": self.model,
                "messages": messages,
                token_param: self.max_tokens,
                "temperature": self.temperature,
            }

            # thinking/reasoning 모델: reasoning_effort 파라미터 추가
            effort = reasoning_effort or ""
            if effort and self.reasoning_levels and effort in self.reasoning_levels:
                kwargs["reasoning_effort"] = effort
                logger.info(f"ChatGPT reasoning_effort={effort}")

            response = client.chat.completions.create(**kwargs)
            model_used = getattr(response, "model", self.model)
            thinking_flag = " [thinking]" if self.thinking_enabled else ""
            logger.info(f"ChatGPT 응답 (API, 토큰 과금, model={model_used}{thinking_flag})")
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"ChatGPT API 호출 실패: {e}")
            return None


class ClaudeClient:
    """Anthropic Claude — Claude Code CLI(구독) 우선, API fallback.

    v3.1: 모델별 thinking/reasoning 자동 감지 + extended thinking 지원.
    """

    # Claude Code CLI 경로 (한 번만 탐색)
    _claude_cli_path: Optional[str] = None
    _cli_searched: bool = False

    def __init__(self, config: dict, routing_config: dict | None = None,
                 model_info: ModelInfo | None = None):
        self.model = config.get("model", "claude-sonnet-4-20250514")
        self.cli_model_default = config.get("cli_model", "sonnet")  # CLI 기본 모델
        self.max_tokens = config.get("max_tokens", 4096)
        self.temperature = config.get("temperature", 0.7)
        self.top_p = config.get("top_p", 1.0)
        self.thinking_budget = config.get("thinking_budget", 10000)
        self.prefer_subscription = config.get("prefer_subscription", True)
        # 작업별 모델 오버라이드 (opus/sonnet 분리)
        self._model_override = (routing_config or {}).get("cli_model_override", {})
        # 모델 레지스트리 정보
        self._model_info = model_info
        self.thinking_enabled = model_info.thinking if model_info else True
        self.reasoning_levels = model_info.reasoning_levels if model_info else ["low", "medium", "high"]
        if not ClaudeClient._cli_searched:
            ClaudeClient._claude_cli_path = self._find_claude_cli()
            ClaudeClient._cli_searched = True

    @staticmethod
    def _find_claude_cli() -> Optional[str]:
        """Claude Code CLI 경로 탐색."""
        # PATH에서 찾기
        found = shutil.which("claude")
        if found:
            return found
        # Windows 기본 설치 경로
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            import glob
            pattern = os.path.join(appdata, "Claude", "claude-code", "*", "claude.exe")
            matches = sorted(glob.glob(pattern), reverse=True)
            if matches:
                return matches[0]  # 최신 버전
        return None

    def _resolve_cli_model(self, task_type: str = "") -> str:
        """작업 유형에 따라 CLI 모델 결정 (할당량 관리)."""
        if task_type and task_type in self._model_override:
            return self._model_override[task_type]
        return self.cli_model_default

    def generate(
        self,
        prompt: str,
        system: str = "",
        task_type: str = "",
        use_thinking: bool = False,
    ) -> Optional[str]:
        if use_thinking and self.thinking_enabled:
            result = self._call_api(prompt, system, use_thinking=True)
            if result:
                return result
            logger.warning("Claude thinking 요청을 API로 처리하지 못해 기본 경로로 fallback")

        # 1순위: Claude Code CLI (구독 쿼터, $0)
        if self.prefer_subscription and ClaudeClient._claude_cli_path:
            result = self._call_cli(prompt, system, task_type)
            if result:
                return result
            logger.info("Claude CLI 실패 → API fallback")

        # 2순위: API
        return self._call_api(prompt, system)

    def _call_cli(self, prompt: str, system: str = "", task_type: str = "") -> Optional[str]:
        """Claude Code CLI로 Pro/Max 구독 쿼터 사용."""
        cli_model = self._resolve_cli_model(task_type)
        try:
            full_prompt = f"{system}\n\n{prompt}" if system else prompt
            cmd = [
                ClaudeClient._claude_cli_path,
                "-p", full_prompt,
                "--model", cli_model,
                "--output-format", "text",
            ]
            # ANTHROPIC_API_KEY가 설정되어 있으면 CLI가 API로 빠지므로 제거
            env = os.environ.copy()
            env.pop("ANTHROPIC_API_KEY", None)

            result = subprocess.run(
                cmd,
                capture_output=True, text=True, encoding="utf-8",
                timeout=180, errors="replace", env=env,
            )
            if result.returncode == 0 and result.stdout.strip():
                logger.info(f"Claude 응답 (CLI, 구독 쿼터, model={cli_model}, task={task_type or 'general'})")
                return result.stdout.strip()
            if result.stderr:
                logger.warning(f"Claude CLI stderr: {result.stderr[:200]}")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("Claude CLI 타임아웃 (180초)")
            return None
        except Exception as e:
            logger.warning(f"Claude CLI 호출 실패: {e}")
            return None

    def _call_api(self, prompt: str, system: str = "",
                  use_thinking: bool = False) -> Optional[str]:
        """Anthropic API로 호출 (토큰 과금).

        use_thinking: True면 extended thinking 활성화 (심화 분석 작업에 사용).
        파라미터는 config에서 읽음 (temperature, top_p, thinking_budget, max_tokens).
        """
        api_key = get_env_value("ANTHROPIC_API_KEY")
        if not api_key:
            logger.error("ANTHROPIC_API_KEY 환경변수 없음 (API fallback 불가)")
            return None
        try:
            import anthropic
        except ImportError:
            logger.error("anthropic 패키지 미설치")
            return None

        client = anthropic.Anthropic(api_key=api_key)
        try:
            kwargs: dict = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = system

            # extended thinking 활성화
            if use_thinking and self.thinking_enabled:
                budget_tokens = min(self.thinking_budget, max(self.max_tokens - 1024, 1))
                if budget_tokens != self.thinking_budget:
                    logger.warning(
                        "Claude thinking budget 조정: requested=%s applied=%s max_tokens=%s",
                        self.thinking_budget,
                        budget_tokens,
                        self.max_tokens,
                    )
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": budget_tokens,
                }
                # thinking 모드에서는 temperature를 1로 설정해야 함
                kwargs["temperature"] = 1
                logger.info(f"Claude extended thinking 활성화 (budget={budget_tokens})")
            else:
                # 일반 모드: config에서 읽은 파라미터 적용
                kwargs["temperature"] = self.temperature
                if self.top_p < 1.0:
                    kwargs["top_p"] = self.top_p

            message = client.messages.create(**kwargs)

            # thinking 블록이 있으면 text 블록만 추출
            text_parts = []
            for block in message.content:
                if getattr(block, "type", None) == "text":
                    text_parts.append(block.text)
            result = "\n".join(text_parts).strip()

            thinking_flag = " [thinking]" if use_thinking else ""
            logger.info(f"Claude 응답 (API, 토큰 과금{thinking_flag})")
            return result
        except Exception as e:
            logger.error(f"Claude API 호출 실패: {e}")
            return None


class LLMRouter:
    """작업 유형에 따라 LM Studio / ChatGPT / Claude를 선택하여 호출 (3-tier).

    v3.1: ModelRegistry 연동 — API에서 모델 목록 동적 조회.
    v3.2: Ollama → LM Studio 전환.
    """

    def __init__(self, config: dict):
        llm_cfg = config.get("llm", {})
        routing = llm_cfg.get("routing", {})

        # 모델 레지스트리 초기화 (API에서 모델 세부정보 조회)
        self.registry = ModelRegistry(config)

        # ChatGPT/Claude 모델 정보를 레지스트리에서 조회
        gpt_model_id = llm_cfg.get("chatgpt", {}).get("model", "gpt-5.4")
        claude_model_id = llm_cfg.get("claude", {}).get("model", "claude-sonnet-4-20250514")
        gpt_info = self.registry.find_model(gpt_model_id)
        claude_info = self.registry.find_model(claude_model_id)

        self.lmstudio = LMStudioClient(llm_cfg.get("lmstudio", {}))
        self.router_backend = ExternalRouterClient(llm_cfg.get("router", {}))
        self.chatgpt = ChatGPTClient(llm_cfg.get("chatgpt", {}), model_info=gpt_info)
        self.claude = ClaudeClient(llm_cfg.get("claude", {}), routing_config=routing, model_info=claude_info)
        self._lmstudio_available: Optional[bool] = None
        # 작업별 reasoning 레벨 오버라이드 (대시보드에서 설정)
        self._reasoning_override: dict[str, str] = routing.get("reasoning_override", {})
        self._router_tasks = set(routing.get("router_tasks", []))
        self._lmstudio_tasks = set(routing.get("lmstudio_tasks", [
            "collect", "classify", "caption", "extract_keywords",
            "summarize_draft", "translate_term", "summarize", "draft",
        ]))
        self._chatgpt_tasks = set(routing.get("chatgpt_tasks", [
            "gap_analysis", "study_plan", "supplement",
            "cross_subject", "paper_analysis",
        ]))
        self._claude_tasks = set(routing.get("claude_tasks", [
            "synthesis_final", "quiz_generate", "mechanism",
            "user_response", "pubmed_overview",
            # v2 호환
            "quiz", "synthesis_deep",
        ]))

    def _check_lmstudio(self) -> bool:
        if self._lmstudio_available is None:
            self._lmstudio_available = self.lmstudio.is_available()
            if not self._lmstudio_available:
                logger.info("LM Studio 비활성 → 상위 tier fallback 사용")
        return self._lmstudio_available

    # 심화 분석이 필요한 작업 → extended thinking 자동 활성화
    _THINKING_TASKS = frozenset({"synthesis_deep", "synthesis_final", "mechanism", "gap_analysis"})
    # 높은 추론 레벨이 필요한 작업
    _HIGH_REASONING_TASKS = frozenset({"synthesis_deep", "mechanism", "quiz_generate"})

    def generate(
        self,
        prompt: str,
        task_type: str = "general",
        system: str = "",
        fallback: bool = True,
        images: list[str] | None = None,
        reasoning_effort: str = "",
    ) -> Optional[str]:
        """task_type에 따라 적절한 LLM을 선택하여 호출.

        3-tier 라우팅:
          - LM Studio 작업: collect, classify, caption, ... → LM Studio → ChatGPT → Claude
          - ChatGPT 작업: gap_analysis, study_plan, ... → ChatGPT → Claude
          - Claude 작업: synthesis_final, quiz_generate, ... → Claude only
          - general → LM Studio → ChatGPT → Claude (fallback chain)

        v3.1: thinking/reasoning 자동 감지
          - 심화 작업은 extended thinking 자동 활성화
          - reasoning_effort: "low"/"medium"/"high" (빈 문자열이면 자동 결정)
        """
        # 추론 레벨: 대시보드 설정 > 파라미터 > 자동 결정
        config_reason = self._reasoning_override.get(task_type, "")
        if config_reason and config_reason != "auto":
            reasoning_effort = config_reason
        elif not reasoning_effort and task_type in self._HIGH_REASONING_TASKS:
            reasoning_effort = "high"

        # thinking 필요 여부: high reasoning이면 thinking도 활성화
        use_thinking = task_type in self._THINKING_TASKS or reasoning_effort == "high"

        # ── Claude 전용 작업 ──
        if task_type in self._router_tasks:
            result = self.router_backend.generate(prompt, system, task_type=task_type)
            if result:
                return result
            logger.warning(f"External router 실패 (task={task_type}), fallback chain")

        if task_type in self._claude_tasks:
            result = self.claude.generate(
                prompt,
                system,
                task_type=task_type,
                use_thinking=use_thinking,
            )
            if result:
                return result
            logger.error(f"Claude 실패 (task={task_type})")
            return None

        # ── ChatGPT 전용 작업 ──
        if task_type in self._chatgpt_tasks:
            result = self.chatgpt.generate(
                prompt,
                system,
                reasoning_effort=reasoning_effort,
            )
            if result:
                return result
            logger.warning(f"ChatGPT 실패 (task={task_type}), Claude fallback")
            if fallback:
                return self.claude.generate(
                    prompt,
                    system,
                    task_type=task_type,
                    use_thinking=use_thinking,
                )
            return None

        # ── LM Studio 우선 작업 ──
        if task_type in self._lmstudio_tasks and self._check_lmstudio():
            result = self.lmstudio.generate(prompt, system, images=images)
            if result:
                return result
            logger.warning(f"LM Studio 실패 (task={task_type}), ChatGPT fallback")
            if fallback:
                result = self.chatgpt.generate(
                    prompt,
                    system,
                    reasoning_effort=reasoning_effort,
                )
                if result:
                    return result
                return self.claude.generate(
                    prompt,
                    system,
                    task_type=task_type,
                    use_thinking=use_thinking,
                )
            return None

        # ── general: 전체 fallback chain ──
        if self._check_lmstudio():
            result = self.lmstudio.generate(prompt, system, images=images)
            if result:
                return result

        if fallback:
            result = self.chatgpt.generate(
                prompt,
                system,
                reasoning_effort=reasoning_effort,
            )
            if result:
                return result
            return self.claude.generate(
                prompt,
                system,
                task_type=task_type,
                use_thinking=use_thinking,
            )

        return None

    def generate_json(
        self,
        prompt: str,
        task_type: str = "general",
        system: str = "",
    ) -> Optional[dict]:
        """JSON 응답을 파싱하여 반환."""
        raw = self.generate(prompt, task_type, system)
        if raw is None:
            return None

        # JSON 펜스 제거
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 소형 모델이 생성하는 잘못된 이스케이프 시퀀스 복구
        try:
            repaired = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', text)
            result = json.loads(repaired)
            logger.debug("JSON repair 성공 (invalid escape 수정)")
            return result
        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패: {e}")
            logger.debug(f"응답 앞 200자: {text[:200]}")
            return None

    def generate_with(
        self,
        provider: str,
        prompt: str,
        system: str = "",
    ) -> Optional[str]:
        """특정 provider를 직접 지정하여 호출."""
        if provider == "lmstudio":
            return self.lmstudio.generate(prompt, system)
        elif provider == "router":
            return self.router_backend.generate(prompt, system)
        elif provider == "chatgpt":
            return self.chatgpt.generate(prompt, system)
        elif provider == "claude":
            return self.claude.generate(prompt, system)
        else:
            logger.error(f"알 수 없는 provider: {provider}")
            return None
