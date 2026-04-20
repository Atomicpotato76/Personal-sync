#!/usr/bin/env python3
"""Stage 4 verifier: pedagogy/style/coverage/provenance 검증.

Coverage는 3단 계층 매칭 (substring → alias → semantic).
"""

from __future__ import annotations

import json
import logging
import math
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import yaml

from llm_router import LLMRouter
from path_utils import resolve_path

LOGGER = logging.getLogger("pipeline")
SCRIPT_DIR = Path(__file__).resolve().parent
PEDAGOGY_RULES_PATH = SCRIPT_DIR / "templates" / "pedagogy_rules.yaml"
VERIFIER_SYSTEM_PATH = SCRIPT_DIR / "templates" / "verifier_system.txt"
HALLUCINATED_STATE_RE = re.compile(
    r"(?im)^\s*[-*]?\s*(?:mastery|학습\s*진행률|복습\s*일정|next[_\s-]?review|study\s*progress)\s*[:=].*$"
)


# ── Config ────────────────────────────────────────────────────
@dataclass
class VerifierConfig:
    enabled: bool = False
    max_retries: int = 2
    model: str = "sonnet"
    checks: dict[str, bool] | None = None
    coverage_threshold: float = 0.7
    llm_quick_scan: bool = True
    semantic_matching: bool = True
    semantic_threshold: float = 0.75
    topic_aliases_file: str = "templates/topic_aliases.yaml"

    @classmethod
    def from_config(cls, config: dict) -> "VerifierConfig":
        raw = config.get("verifier", {}) or {}
        return cls(
            enabled=bool(raw.get("enabled", False)),
            max_retries=int(raw.get("max_retries", 2)),
            model=str(raw.get("model", "sonnet")),
            checks=raw.get("checks") or {},
            coverage_threshold=float(raw.get("coverage_threshold", 0.7)),
            llm_quick_scan=bool(raw.get("llm_quick_scan", True)),
            semantic_matching=bool(raw.get("semantic_matching", True)),
            semantic_threshold=float(raw.get("semantic_threshold", 0.75)),
            topic_aliases_file=str(raw.get("topic_aliases_file", "templates/topic_aliases.yaml")),
        )


# ── Pedagogy rules ────────────────────────────────────────────
def _load_pedagogy_rules(path: Path = PEDAGOGY_RULES_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = data.get("rules", [])
    return [r for r in rules if isinstance(r, dict)]


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


# ── Check: pedagogy ───────────────────────────────────────────
def check_pedagogy(text: str, rules: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    for idx, line in enumerate(_split_lines(text), start=1):
        for rule in rules:
            patterns = [re.compile(p, re.IGNORECASE) for p in rule.get("patterns", [])]
            exclude_patterns = [re.compile(p, re.IGNORECASE) for p in rule.get("exclude_patterns", [])]
            if patterns and all(p.search(line) for p in patterns):
                if exclude_patterns and any(p.search(line) for p in exclude_patterns):
                    continue
                issues.append(
                    {
                        "location": f"line {idx}",
                        "text": line,
                        "problem": str(rule.get("problem", "pedagogy 규칙 위반")),
                        "suggestion": str(rule.get("suggestion", "교재 용어 프레이밍으로 수정")),
                    }
                )
    return {"pass": len(issues) == 0, "issues": issues}


# ── Check: style alignment ────────────────────────────────────
def check_style_alignment(text: str) -> dict[str, Any]:
    generic_patterns = [
        re.compile(r"에너지.{0,15}(높은|고).{0,15}(낮은|저)", re.IGNORECASE),
        re.compile(r"energy.{0,20}(high).{0,20}(low)", re.IGNORECASE),
        re.compile(r"(thermodynamic|entropy|energy minimization)", re.IGNORECASE),
    ]
    textbook_patterns = [
        re.compile(r"stronger\s+acid.{0,20}weaker\s+acid", re.IGNORECASE),
        re.compile(r"stronger\s+base.{0,20}weaker\s+base", re.IGNORECASE),
        re.compile(r"weaker acid-?weaker base", re.IGNORECASE),
    ]
    deviations: list[dict[str, str]] = []
    for idx, line in enumerate(_split_lines(text), start=1):
        if any(p.search(line) for p in generic_patterns) and not any(p.search(line) for p in textbook_patterns):
            deviations.append(
                {
                    "location": f"line {idx}",
                    "llm_phrasing": line[:200],
                    "textbook_phrasing": "stronger acid/base → weaker acid/base",
                    "severity": "minor",
                }
            )
    return {"pass": len(deviations) == 0, "deviations": deviations}


# ── Coverage helpers (3-layer: substring → alias → semantic) ──
def _chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    clean = " ".join((text or "").split())
    if not clean:
        return []
    return [clean[i : i + chunk_size] for i in range(0, len(clean), chunk_size)]


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _load_topic_aliases(config: dict[str, Any]) -> dict[str, list[str]]:
    verifier_cfg = config.get("verifier", {}) if isinstance(config, dict) else {}
    alias_file = verifier_cfg.get("topic_aliases_file", "templates/topic_aliases.yaml")

    scripts_dir = Path(config.get("scripts_dir", Path(__file__).resolve().parent))
    alias_path = resolve_path(alias_file, scripts_dir)
    if not alias_path.exists():
        return {}

    with alias_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}

    if not isinstance(loaded, dict):
        return {}

    normalized: dict[str, list[str]] = {}
    for topic, aliases in loaded.items():
        if isinstance(topic, str) and isinstance(aliases, list):
            normalized[topic] = [alias for alias in aliases if isinstance(alias, str)]
    return normalized


def _is_mem0_remote_chroma_healthy(config: dict[str, Any], timeout_sec: float = 0.4) -> bool:
    mem0_cfg = config.get("mem0", {}) if isinstance(config, dict) else {}
    vector_store = mem0_cfg.get("vector_store", {})
    if vector_store.get("mode", "local") != "remote":
        return True

    host = str(vector_store.get("host", "")).strip()
    port = int(vector_store.get("port", 8000))
    if not host:
        return False

    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def _embedding_cosine(
    topic: str,
    corpus_chunks: list[str],
    embedder_cfg: dict[str, Any],
    timeout_sec: float = 6.0,
) -> tuple[float, str] | None:
    if not topic or not corpus_chunks:
        return None

    base_url = str(embedder_cfg.get("base_url", "")).strip()
    model = str(embedder_cfg.get("model", "")).strip()
    api_key = str(embedder_cfg.get("api_key", "")).strip() or "lm-studio"
    if not base_url or not model:
        return None

    endpoint = f"{base_url.rstrip('/')}/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        topic_resp = requests.post(
            endpoint,
            json={"model": model, "input": topic},
            headers=headers,
            timeout=timeout_sec,
        )
        topic_resp.raise_for_status()
        topic_emb = topic_resp.json()["data"][0]["embedding"]

        chunk_resp = requests.post(
            endpoint,
            json={"model": model, "input": corpus_chunks},
            headers=headers,
            timeout=timeout_sec,
        )
        chunk_resp.raise_for_status()
        chunk_embeddings = [row["embedding"] for row in chunk_resp.json().get("data", [])]

        if not chunk_embeddings:
            return None

        best_score = -1.0
        best_chunk = ""
        for chunk, embedding in zip(corpus_chunks, chunk_embeddings):
            score = _cosine_similarity(topic_emb, embedding)
            if score > best_score:
                best_score = score
                best_chunk = chunk
        return best_score, best_chunk
    except Exception:
        return None


# ── Check: coverage (3-layer) ─────────────────────────────────
def _collect_required_topics(config: dict, subject: str) -> list[str]:
    subject_cfg = (config.get("subjects", {}) or {}).get(subject, {}) or {}
    verifier_cfg = config.get("verifier", {}) or {}
    explicit = verifier_cfg.get("required_topics", {}).get(subject)
    if isinstance(explicit, list) and explicit:
        return [str(t) for t in explicit]

    chapter_topics = (
        subject_cfg.get("chapters", {})
        .get("ch1", {})
        .get("required_topics", [])
    )
    return [str(t) for t in chapter_topics] if isinstance(chapter_topics, list) else []


def check_coverage(note_text: str, synthesis: str, config: dict, subject: str) -> dict[str, Any]:
    required_topics = _collect_required_topics(config, subject)
    corpus = f"{note_text}\n\n{synthesis}".lower()

    verifier_cfg = config.get("verifier", {}) or {}
    semantic_enabled = bool(verifier_cfg.get("semantic_matching", True))
    semantic_threshold = float(verifier_cfg.get("semantic_threshold", 0.75))
    coverage_threshold = float(verifier_cfg.get("coverage_threshold", 0.7))
    aliases = _load_topic_aliases(config)

    # Layer 3 준비: mem0 embedder 서버 건강 확인
    if semantic_enabled and not _is_mem0_remote_chroma_healthy(config):
        semantic_enabled = False

    chunks = _chunk_text(f"{note_text}\n\n{synthesis}") if semantic_enabled else []
    embedder_cfg = config.get("mem0", {}).get("embedder", {}) if semantic_enabled else {}

    covered: list[str] = []
    covered_detail: list[dict[str, str]] = []
    missing: list[str] = []

    for topic in required_topics:
        topic_lower = topic.lower()

        # Layer 1: substring 매칭
        if topic_lower in corpus:
            covered.append(topic)
            covered_detail.append({"topic": topic, "method": "substring", "evidence": topic})
            continue

        # Layer 2: alias dictionary 매칭
        topic_aliases = aliases.get(topic, [])
        matched_alias = next((alias for alias in topic_aliases if alias.lower() in corpus), None)
        if matched_alias:
            covered.append(topic)
            covered_detail.append({
                "topic": topic,
                "method": f"alias:{matched_alias}",
                "evidence": matched_alias,
            })
            continue

        # Layer 3: semantic similarity (mem0 embedder 재활용)
        if semantic_enabled:
            semantic_result = _embedding_cosine(topic, chunks, embedder_cfg)
            if semantic_result is not None:
                score, best_chunk = semantic_result
                if score >= semantic_threshold:
                    covered.append(topic)
                    covered_detail.append({
                        "topic": topic,
                        "method": f"semantic:{score:.2f}",
                        "evidence": best_chunk[:200],
                    })
                    continue

        missing.append(topic)

    return {
        "pass": (len(covered) / max(len(required_topics), 1)) >= coverage_threshold,
        "required_topics": required_topics,
        "covered": covered,
        "covered_detail": covered_detail,
        "missing": missing,
    }


# ── Check: provenance ─────────────────────────────────────────
def check_provenance_claims(synthesis: str) -> dict[str, Any]:
    false_claims = [line for line in synthesis.splitlines() if HALLUCINATED_STATE_RE.search(line)]
    return {"pass": len(false_claims) == 0, "false_claims": false_claims}


def check_provenance_tags(synthesis: str) -> dict[str, Any]:
    mistagged: list[str] = []
    for line in synthesis.splitlines():
        if "[" in line and "]" in line and "★" in line:
            if not re.search(r"\[(S|D|E)\]\s*★{1,3}", line):
                mistagged.append(line.strip())
    return {"pass": len(mistagged) == 0, "mistagged": mistagged}


# ── Scoring & fix instructions ────────────────────────────────
def _compose_fix_instructions(checks: dict[str, Any]) -> str:
    parts: list[str] = []
    if not checks["pedagogy"]["pass"]:
        parts.append("용어 정확성: lone pair/bonding pair를 분리해 교재 정의에 맞게 재작성.")
    if not checks["style_alignment"]["pass"]:
        parts.append("스타일: 에너지 일반론 대신 교재의 stronger→weaker acid/base 프레이밍으로 수정.")
    if not checks["coverage"]["pass"]:
        missing = ", ".join(checks["coverage"].get("missing", [])[:8])
        parts.append(f"커버리지: 누락 토픽을 최소 요약+문항으로 추가 ({missing}).")
    if not checks["provenance_claims"]["pass"]:
        parts.append("근거 없는 사용자 상태(mastery/next_review 등) 문장을 삭제.")
    if not checks["provenance_tags"]["pass"]:
        parts.append("문단 말미 provenance 태그를 [S]/[D]/[E] + ★ 형식으로 정정.")
    return "\n".join(f"- {p}" for p in parts) if parts else "- 수정 필요 없음."


def _score(checks: dict[str, Any]) -> int:
    weights = {
        "pedagogy": 30,
        "style_alignment": 20,
        "coverage": 25,
        "provenance_claims": 15,
        "provenance_tags": 10,
    }
    score = 0
    for key, weight in weights.items():
        if checks.get(key, {}).get("pass", False):
            score += weight
    return int(score)


# ── LLM quick scan ────────────────────────────────────────────
def _run_llm_quick_scan(result: dict[str, Any], config: dict, note_text: str, synthesis: str) -> dict[str, Any]:
    if not (config.get("verifier", {}) or {}).get("llm_quick_scan", True):
        return result
    if not VERIFIER_SYSTEM_PATH.exists():
        return result
    try:
        system_prompt = VERIFIER_SYSTEM_PATH.read_text(encoding="utf-8")
        prompt = (
            "아래 deterministic 결과를 유지하면서 누락된 이슈만 보강하세요. "
            "반드시 JSON만 출력, 2000 tokens 이내.\n\n"
            f"[deterministic]\n{json.dumps(result, ensure_ascii=False)}\n\n"
            f"[note]\n{note_text[:3500]}\n\n[synthesis]\n{synthesis[:3500]}"
        )
        router = LLMRouter(config)
        llm_result = router.generate_json(prompt, task_type="quiz", system=system_prompt)
        if isinstance(llm_result, dict) and llm_result.get("checks"):
            llm_checks = llm_result.get("checks")
            if isinstance(llm_checks, dict):
                deterministic_checks = result.get("checks", {})
                deterministic_coverage = deterministic_checks.get("coverage")
                if isinstance(deterministic_coverage, dict):
                    llm_checks["coverage"] = deterministic_coverage

                llm_result["checks"] = llm_checks
                llm_result["score"] = _score(llm_checks)
                llm_result["verdict"] = "PASS" if all(
                    check.get("pass", False)
                    for check in llm_checks.values()
                    if isinstance(check, dict)
                ) else "FAIL"
                return llm_result
    except Exception as exc:
        LOGGER.warning("Verifier LLM quick scan 실패: %s", exc)
    return result


# ── Main entry ────────────────────────────────────────────────
def verify_note_and_quiz(note_text: str, synthesis: str, config: dict, subject: str) -> dict[str, Any]:
    rules = _load_pedagogy_rules()
    checks = {
        "pedagogy": check_pedagogy(synthesis, rules),
        "style_alignment": check_style_alignment(synthesis),
        "coverage": check_coverage(note_text, synthesis, config, subject),
        "provenance_claims": check_provenance_claims(synthesis),
        "provenance_tags": check_provenance_tags(synthesis),
    }
    result = {
        "verdict": "PASS" if all(v.get("pass", False) for v in checks.values()) else "FAIL",
        "score": _score(checks),
        "checks": checks,
        "fix_instructions": _compose_fix_instructions(checks),
    }
    return _run_llm_quick_scan(result, config, note_text, synthesis)


def save_verification_report(report: dict[str, Any], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
