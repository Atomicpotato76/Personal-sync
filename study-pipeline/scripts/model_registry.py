#!/usr/bin/env python3
"""model_registry.py -- OpenAI / Anthropic 모델 목록을 API에서 동적으로 조회.

모델별 세부 정보:
  - thinking 지원 여부
  - 변형(instant, thinking, pro 등)
  - 추론 레벨(reasoning_effort)
  - 가격 등급
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from env_utils import get_env_value

logger = logging.getLogger("pipeline")

# ══════════════════════════════════════════════════════════════
# 데이터 모델
# ══════════════════════════════════════════════════════════════

@dataclass
class ModelInfo:
    """단일 모델의 메타 정보."""
    id: str                          # API model ID (e.g. "gpt-5.4-thinking")
    provider: str                    # "openai" | "anthropic" | "lmstudio"
    display_name: str                # 사용자 표시명
    family: str = ""                 # 모델 계열 (e.g. "gpt-5.4", "claude-4.6")
    variant: str = ""                # 변형 (e.g. "instant", "thinking", "pro", "")
    thinking: bool = False           # extended thinking / chain-of-thought 지원
    reasoning_levels: list[str] = field(default_factory=list)  # ["low","medium","high"]
    tier: str = ""                   # "opus"/"sonnet"/"haiku" (Anthropic) 또는 가격 등급
    max_tokens: int = 4096
    context_window: int = 0
    is_available: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "provider": self.provider,
            "display_name": self.display_name,
            "family": self.family,
            "variant": self.variant,
            "thinking": self.thinking,
            "reasoning_levels": self.reasoning_levels,
            "tier": self.tier,
            "max_tokens": self.max_tokens,
            "context_window": self.context_window,
            "is_available": self.is_available,
        }


# ══════════════════════════════════════════════════════════════
# OpenAI 모델 조회
# ══════════════════════════════════════════════════════════════

# GPT 5.x 변형 패턴 → thinking / reasoning 매핑
_GPT_VARIANT_META: dict[str, dict] = {
    "":         {"thinking": False, "reasoning_levels": [],                        "tier": "standard"},
    "instant":  {"thinking": False, "reasoning_levels": [],                        "tier": "fast"},
    "thinking": {"thinking": True,  "reasoning_levels": ["low", "medium", "high"], "tier": "reasoning"},
    "pro":      {"thinking": True,  "reasoning_levels": ["low", "medium", "high"], "tier": "pro"},
    "mini":     {"thinking": False, "reasoning_levels": ["low", "medium"],         "tier": "mini"},
}

# GPT 모델 ID 파싱: gpt-5.4, gpt-5.4-instant, gpt-5.4-thinking, gpt-5.4-pro 등
_GPT_PATTERN = re.compile(
    r"^(gpt-[\d.]+)(?:-(instant|thinking|pro|mini))?(?:-(\d{4}-\d{2}-\d{2}))?$"
)

# o-시리즈 (reasoning 모델): o3, o4-mini 등
_O_PATTERN = re.compile(r"^(o[\d]+)(?:-(mini|pro))?(?:-(\d{4}-\d{2}-\d{2}))?$")


def _parse_openai_model(model_id: str) -> Optional[ModelInfo]:
    """OpenAI 모델 ID를 파싱하여 ModelInfo 생성."""
    # GPT 계열
    m = _GPT_PATTERN.match(model_id)
    if m:
        family = m.group(1)       # "gpt-5.4"
        variant = m.group(2) or ""  # "instant", "thinking", "pro", ""
        meta = _GPT_VARIANT_META.get(variant, _GPT_VARIANT_META[""])

        # display name 생성
        parts = [family.upper()]
        if variant:
            parts.append(variant.capitalize())
        display = " ".join(parts)

        return ModelInfo(
            id=model_id,
            provider="openai",
            display_name=display,
            family=family,
            variant=variant,
            thinking=meta["thinking"],
            reasoning_levels=meta["reasoning_levels"],
            tier=meta["tier"],
            context_window=_guess_openai_context(family, variant),
        )

    # o-시리즈 (reasoning 전용)
    m = _O_PATTERN.match(model_id)
    if m:
        family = m.group(1)
        variant = m.group(2) or ""
        display = family.upper() + (f" {variant.capitalize()}" if variant else "")
        return ModelInfo(
            id=model_id,
            provider="openai",
            display_name=display,
            family=family,
            variant=variant,
            thinking=True,
            reasoning_levels=["low", "medium", "high"],
            tier="reasoning",
            context_window=200_000,
        )

    return None


def _guess_openai_context(family: str, variant: str) -> int:
    """모델 계열+변형으로 context window 추정."""
    if "5.4" in family or "5." in family:
        if variant == "pro":
            return 1_000_000
        return 256_000
    return 128_000


def fetch_openai_models(api_key: str | None = None) -> list[ModelInfo]:
    """OpenAI /v1/models API로 사용 가능한 GPT/o 모델 목록 조회."""
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        logger.debug("OpenAI API key 없음 → 모델 목록 조회 건너뜀")
        return _fallback_openai_models()

    try:
        r = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if r.status_code != 200:
            logger.warning(f"OpenAI models API 실패: {r.status_code}")
            return _fallback_openai_models()

        data = r.json().get("data", [])
        models = []
        seen_families = set()
        for item in data:
            mid = item.get("id", "")
            info = _parse_openai_model(mid)
            if info:
                models.append(info)
                seen_families.add(info.family)

        # 날짜 스냅샷 제거 (최신만 유지)
        deduped = _dedupe_dated_models(models)
        logger.info(f"OpenAI 모델 {len(deduped)}개 조회 완료 (families: {seen_families})")
        return deduped if deduped else _fallback_openai_models()

    except Exception as e:
        logger.warning(f"OpenAI models API 오류: {e}")
        return _fallback_openai_models()


def _dedupe_dated_models(models: list[ModelInfo]) -> list[ModelInfo]:
    """같은 family+variant에서 날짜 없는 ID를 우선 보존."""
    best: dict[str, ModelInfo] = {}
    for m in models:
        key = f"{m.family}|{m.variant}"
        existing = best.get(key)
        if existing is None:
            best[key] = m
        elif len(m.id) < len(existing.id):
            # 날짜 suffix 없는 짧은 ID 우선
            best[key] = m
    return sorted(best.values(), key=lambda x: (x.family, x.variant))


def _fallback_openai_models() -> list[ModelInfo]:
    """API 연결 불가 시 알려진 모델 하드코딩 반환."""
    models = []
    for variant, meta in _GPT_VARIANT_META.items():
        mid = f"gpt-5.4{'-' + variant if variant else ''}"
        display = f"GPT-5.4{' ' + variant.capitalize() if variant else ''}"
        models.append(ModelInfo(
            id=mid,
            provider="openai",
            display_name=display,
            family="gpt-5.4",
            variant=variant,
            thinking=meta["thinking"],
            reasoning_levels=meta["reasoning_levels"],
            tier=meta["tier"],
            context_window=_guess_openai_context("gpt-5.4", variant),
            is_available=False,  # API 미확인
        ))
    return models


# ══════════════════════════════════════════════════════════════
# Anthropic 모델 조회
# ══════════════════════════════════════════════════════════════

# Anthropic 모델 ID 패턴
_CLAUDE_PATTERN = re.compile(
    r"^claude-(opus|sonnet|haiku)-(\d+(?:[.-]\d+)?)(?:-(\d{8}))?$"
)

# 티어별 메타데이터
_CLAUDE_TIER_META: dict[str, dict] = {
    "opus":   {"thinking": True, "reasoning_levels": ["low", "medium", "high"],
               "tier": "opus",  "context_window": 1_000_000, "max_tokens": 32_000},
    "sonnet": {"thinking": True, "reasoning_levels": ["low", "medium", "high"],
               "tier": "sonnet", "context_window": 200_000, "max_tokens": 16_000},
    "haiku":  {"thinking": True, "reasoning_levels": ["low", "medium"],
               "tier": "haiku",  "context_window": 200_000, "max_tokens": 8_192},
}


def _parse_claude_model(model_id: str) -> Optional[ModelInfo]:
    """Anthropic 모델 ID 파싱."""
    m = _CLAUDE_PATTERN.match(model_id)
    if not m:
        return None

    tier_name = m.group(1)
    version = m.group(2).replace("-", ".")

    meta = _CLAUDE_TIER_META.get(tier_name, _CLAUDE_TIER_META["sonnet"])
    family = f"claude-{version}"
    display = f"Claude {version.replace('-', '.')} {tier_name.capitalize()}"

    return ModelInfo(
        id=model_id,
        provider="anthropic",
        display_name=display,
        family=family,
        variant=tier_name,
        thinking=meta["thinking"],
        reasoning_levels=meta["reasoning_levels"],
        tier=meta["tier"],
        max_tokens=meta["max_tokens"],
        context_window=meta["context_window"],
    )


def fetch_anthropic_models(api_key: str | None = None) -> list[ModelInfo]:
    """Anthropic API로 모델 목록 조회. 실패 시 fallback."""
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        logger.debug("Anthropic API key 없음 → fallback 모델 사용")
        return _fallback_anthropic_models()

    try:
        r = requests.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
            timeout=10,
        )
        if r.status_code != 200:
            logger.warning(f"Anthropic models API 실패: {r.status_code}")
            return _fallback_anthropic_models()

        data = r.json().get("data", [])
        models = []
        for item in data:
            mid = item.get("id", "")
            info = _parse_claude_model(mid)
            if info:
                # API 응답에서 추가 정보 반영
                if "display_name" in item:
                    info.display_name = item["display_name"]
                models.append(info)

        deduped = _dedupe_claude_models(models)
        logger.info(f"Anthropic 모델 {len(deduped)}개 조회 완료")
        return deduped if deduped else _fallback_anthropic_models()

    except Exception as e:
        logger.warning(f"Anthropic models API 오류: {e}")
        return _fallback_anthropic_models()


def _dedupe_claude_models(models: list[ModelInfo]) -> list[ModelInfo]:
    """같은 티어에서 최신 버전만 유지."""
    best: dict[str, ModelInfo] = {}
    for m in models:
        key = m.tier
        existing = best.get(key)
        if existing is None or m.id > existing.id:
            best[key] = m
    return sorted(best.values(), key=lambda x: ("opus", "sonnet", "haiku").index(x.tier) if x.tier in ("opus", "sonnet", "haiku") else 99)


def _fallback_anthropic_models() -> list[ModelInfo]:
    """API 미연결 시 알려진 Claude 모델 반환."""
    known = [
        ("claude-opus-4-7",            "opus",   "4.7"),
        ("claude-opus-4-6",            "opus",   "4.6"),
        ("claude-sonnet-4-6",          "sonnet", "4.6"),
        ("claude-haiku-4-5-20251001",  "haiku",  "4.5"),
    ]
    models = []
    for mid, tier, ver in known:
        meta = _CLAUDE_TIER_META[tier]
        models.append(ModelInfo(
            id=mid,
            provider="anthropic",
            display_name=f"Claude {ver} {tier.capitalize()}",
            family=f"claude-{ver}",
            variant=tier,
            thinking=meta["thinking"],
            reasoning_levels=meta["reasoning_levels"],
            tier=meta["tier"],
            max_tokens=meta["max_tokens"],
            context_window=meta["context_window"],
            is_available=False,
        ))
    return models


# ══════════════════════════════════════════════════════════════
# LM Studio 모델 조회 (OpenAI 호환 API)
# ══════════════════════════════════════════════════════════════

def fetch_lmstudio_models(base_url: str = "http://localhost:1234") -> list[ModelInfo]:
    """LM Studio /v1/models에서 로드된 모델 목록 조회."""
    try:
        r = requests.get(f"{base_url.rstrip('/')}/v1/models", timeout=5)
        if r.status_code != 200:
            return []

        data = r.json().get("data", [])
        models = []
        for item in data:
            model_id = item.get("id", "")
            if not model_id:
                continue

            models.append(ModelInfo(
                id=model_id,
                provider="lmstudio",
                display_name=model_id,
                family="lmstudio",
                variant="local",
                thinking=False,
                reasoning_levels=[],
                tier="local",
            ))
        return models

    except Exception:
        return []


# ══════════════════════════════════════════════════════════════
# 통합 레지스트리
# ══════════════════════════════════════════════════════════════

class ModelRegistry:
    """3-tier 모델 레지스트리. API에서 모델 목록을 조회하고 캐싱."""

    # 캐시 유효 시간 (5분)
    _CACHE_TTL = 300

    def __init__(self, config: dict):
        self._config = config
        self._cache: dict[str, list[ModelInfo]] = {}
        self._cache_ts: dict[str, float] = {}

        # API 키는 환경변수에서만 로드
        self._openai_key = get_env_value("OPENAI_API_KEY")
        self._anthropic_key = get_env_value("ANTHROPIC_API_KEY")

        llm_cfg = config.get("llm", {})
        self._lmstudio_url = llm_cfg.get("lmstudio", {}).get(
            "base_url",
            os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234"),
        )

    def _is_cache_valid(self, key: str) -> bool:
        ts = self._cache_ts.get(key, 0)
        return (time.time() - ts) < self._CACHE_TTL

    def get_openai_models(self, force: bool = False) -> list[ModelInfo]:
        if not force and self._is_cache_valid("openai"):
            return self._cache["openai"]
        models = fetch_openai_models(self._openai_key)
        self._cache["openai"] = models
        self._cache_ts["openai"] = time.time()
        return models

    def get_anthropic_models(self, force: bool = False) -> list[ModelInfo]:
        if not force and self._is_cache_valid("anthropic"):
            return self._cache["anthropic"]
        models = fetch_anthropic_models(self._anthropic_key)
        self._cache["anthropic"] = models
        self._cache_ts["anthropic"] = time.time()
        return models

    def get_lmstudio_models(self, force: bool = False) -> list[ModelInfo]:
        if not force and self._is_cache_valid("lmstudio"):
            return self._cache["lmstudio"]
        models = fetch_lmstudio_models(self._lmstudio_url)
        self._cache["lmstudio"] = models
        self._cache_ts["lmstudio"] = time.time()
        return models

    def get_all_models(self, force: bool = False) -> dict[str, list[ModelInfo]]:
        return {
            "openai": self.get_openai_models(force),
            "anthropic": self.get_anthropic_models(force),
            "lmstudio": self.get_lmstudio_models(force),
        }

    def find_model(self, model_id: str) -> Optional[ModelInfo]:
        """모델 ID로 검색."""
        for models in self.get_all_models().values():
            for m in models:
                if m.id == model_id:
                    return m
        return None

    def get_openai_thinking_models(self) -> list[ModelInfo]:
        """thinking 지원 OpenAI 모델만 반환."""
        return [m for m in self.get_openai_models() if m.thinking]

    def get_models_by_tier(self, provider: str, tier: str) -> list[ModelInfo]:
        """특정 provider의 특정 tier 모델 반환."""
        models = {
            "openai": self.get_openai_models,
            "anthropic": self.get_anthropic_models,
            "lmstudio": self.get_lmstudio_models,
        }.get(provider, lambda: [])()
        return [m for m in models if m.tier == tier]

    def get_reasoning_capable(self) -> list[ModelInfo]:
        """추론 레벨 지원 모델 전체 반환."""
        result = []
        for models in self.get_all_models().values():
            result.extend(m for m in models if m.reasoning_levels)
        return result

    def summary(self) -> dict:
        """레지스트리 요약 정보 (대시보드용)."""
        all_models = self.get_all_models()
        return {
            provider: {
                "count": len(models),
                "thinking_count": sum(1 for m in models if m.thinking),
                "reasoning_count": sum(1 for m in models if m.reasoning_levels),
                "models": [m.to_dict() for m in models],
            }
            for provider, models in all_models.items()
        }
