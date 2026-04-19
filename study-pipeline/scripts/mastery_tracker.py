#!/usr/bin/env python3
"""mastery_tracker.py -- 퀴즈 실데이터 기반 mastery 상태 집계/저장."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from path_utils import get_study_paths


def _mastery_path(config: dict) -> Path:
    return get_study_paths(config).pipeline / "mastery_status.json"


def load_mastery(config: dict) -> dict[str, Any]:
    path = _mastery_path(config)
    if not path.exists():
        return {"version": 1, "subjects": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "subjects": {}}
        data.setdefault("version", 1)
        data.setdefault("subjects", {})
        return data
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "subjects": {}}


def save_mastery(config: dict, mastery_data: dict[str, Any]) -> None:
    path = _mastery_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mastery_data, f, ensure_ascii=False, indent=2)


def _level_for(mastery: float, green: float, yellow: float) -> str:
    if mastery >= green:
        return "🟢"
    if mastery >= yellow:
        return "🟡"
    return "🔴"


def update_mastery_from_quiz(config: dict, quiz_data: dict[str, Any]) -> bool:
    """리뷰 완료된 quiz JSON으로 mastery_status.json을 누적 갱신."""
    subject = str(quiz_data.get("subject", "unknown"))
    quiz_id = str(quiz_data.get("id", "unknown_quiz"))
    items = quiz_data.get("items", [])
    if not isinstance(items, list):
        return False

    mastery_cfg = config.get("mastery", {})
    green = float(mastery_cfg.get("green_threshold", 0.8))
    yellow = float(mastery_cfg.get("yellow_threshold", 0.5))

    mastery_data = load_mastery(config)
    subjects = mastery_data.setdefault("subjects", {})
    subject_data = subjects.setdefault(subject, {"concepts": {}, "updated_at": None})
    concepts = subject_data.setdefault("concepts", {})

    updated = False
    now = datetime.now().isoformat(timespec="seconds")

    for index, item in enumerate(items):
        review = item.get("review") or {}
        result = review.get("result")
        if result not in {"correct", "partial", "wrong"}:
            continue

        score = 1.0 if result == "correct" else 0.5 if result == "partial" else 0.0
        reviewed_at = str(review.get("reviewed_at") or now)
        tags = item.get("concept_tags") or []
        if not tags:
            tags = ["untagged"]

        for tag in tags:
            concept_tag = str(tag).strip() or "untagged"
            entry = concepts.setdefault(
                concept_tag,
                {
                    "correct_count": 0.0,
                    "total_count": 0,
                    "recent_scores": [],
                    "mastery": 0.0,
                    "level": "🔴",
                    "last_quiz_at": None,
                    "last_quiz_id": None,
                    "attempt_keys": [],
                },
            )

            # 동일 퀴즈/문항/리뷰시각 재반영 방지 (idempotent)
            attempt_key = f"{quiz_id}:{index}:{reviewed_at}:{result}:{concept_tag}"
            attempt_keys: list[str] = entry.setdefault("attempt_keys", [])
            if attempt_key in attempt_keys:
                continue
            attempt_keys.append(attempt_key)
            if len(attempt_keys) > 200:
                del attempt_keys[:-200]

            entry["total_count"] = int(entry.get("total_count", 0)) + 1
            entry["correct_count"] = float(entry.get("correct_count", 0.0)) + score

            recent_scores = entry.setdefault("recent_scores", [])
            recent_scores.append(score)
            if len(recent_scores) > 3:
                del recent_scores[:-3]

            mastery = (
                float(entry["correct_count"]) / float(entry["total_count"])
                if entry["total_count"] > 0
                else 0.0
            )
            entry["mastery"] = round(mastery, 3)
            entry["level"] = _level_for(entry["mastery"], green, yellow)
            entry["last_quiz_at"] = reviewed_at
            entry["last_quiz_id"] = quiz_id
            updated = True

    if updated:
        subject_data["updated_at"] = now
        save_mastery(config, mastery_data)
    return updated


def get_mastery_lines(config: dict, subject: str, limit: int = 10) -> list[str]:
    """학습 계획 프롬프트용 mastery 요약 라인."""
    mastery_data = load_mastery(config)
    subject_data = mastery_data.get("subjects", {}).get(subject, {})
    concepts: dict[str, dict[str, Any]] = subject_data.get("concepts", {})
    if not concepts:
        return []

    ranked = sorted(
        concepts.items(),
        key=lambda x: (
            x[1].get("mastery", 0.0),
            -x[1].get("total_count", 0),
        ),
    )
    lines: list[str] = []
    for concept, info in ranked[:limit]:
        mastery = float(info.get("mastery", 0.0))
        level = str(info.get("level", "🔴"))
        total = int(info.get("total_count", 0))
        correct = float(info.get("correct_count", 0.0))
        recent_scores = info.get("recent_scores", [])
        recent_avg = (sum(recent_scores) / len(recent_scores)) if recent_scores else 0.0
        lines.append(
            f"- {level} {concept}: mastery {mastery:.0%} "
            f"(정답 {correct:g}/{total}, 최근 3회 {recent_avg:.0%})"
        )
    return lines
