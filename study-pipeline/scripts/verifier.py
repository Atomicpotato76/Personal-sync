#!/usr/bin/env python3
"""Stage 4 verifier: pedagogy/style/coverage/provenance 검증.

Coverage는 로컬 규칙 기반 2단 계층 매칭 (substring → alias)을 사용한다.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


# ── Coverage helpers (2-layer: substring → alias) ─────────────
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


# ── Check: coverage (2-layer) ─────────────────────────────────
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
    coverage_threshold = float(verifier_cfg.get("coverage_threshold", 0.7))
    aliases = _load_topic_aliases(config)

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
