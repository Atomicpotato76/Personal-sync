"""concepts.py -- 취약 개념 조회 MCP 도구."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from path_utils import get_study_paths


def _load_weak_concepts(config: dict) -> dict:
    paths = get_study_paths(config)
    wc_path = paths.pipeline / "weak_concepts.json"
    if wc_path.exists():
        with open(wc_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _subject_display(config: dict) -> dict[str, str]:
    mapping = config.get("folder_mapping", {})
    return {v: k for k, v in mapping.items()}


def get_weak_concepts(subject: str, config: dict) -> str:
    """취약 개념 목록 반환."""
    weak = _load_weak_concepts(config)
    display = _subject_display(config)

    if subject:
        subjects = {subject: weak.get(subject, {})}
    else:
        subjects = weak

    if not any(subjects.values()):
        return "취약 개념 데이터가 없습니다. 퀴즈를 풀어 데이터를 축적하세요."

    lines = ["## 취약 개념 현황\n"]

    for subj_key, concepts in subjects.items():
        if not concepts:
            continue
        subj_name = display.get(subj_key, subj_key)
        lines.append(f"### {subj_name} ({subj_key})")

        # priority 순서로 정렬 (high → medium → low)
        priority_order = {"high": 0, "medium": 1, "low": 2}
        sorted_concepts = sorted(
            concepts.items(),
            key=lambda x: (priority_order.get(x[1].get("priority", "low"), 3), x[1].get("mastery", 1)),
        )

        for tag, info in sorted_concepts:
            mastery = info.get("mastery", 0)
            priority = info.get("priority", "?")
            encounters = info.get("encounter_count", 0)
            correct = info.get("correct_count", 0)
            interval = info.get("sr_interval", "?")
            next_review = info.get("sr_next_review", "-")
            ease = info.get("sr_ease_factor", "?")

            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(priority, "⚪")
            lines.append(
                f"- {icon} **{tag}** — mastery: {mastery:.0%} | "
                f"priority: {priority} | "
                f"{correct}/{encounters} correct | "
                f"interval: {interval}일 | "
                f"next: {next_review}"
            )

            # 최근 오답 메모
            mistakes = info.get("recent_mistakes", [])
            if mistakes:
                latest = mistakes[-1]
                lines.append(f"  - 최근 오답: {latest.get('date', '?')[:10]} — {latest.get('memo', '')}")

        lines.append("")

    # 요약 통계
    total = sum(len(c) for c in subjects.values())
    mastered = sum(
        1 for c in subjects.values()
        for info in c.values()
        if info.get("mastery", 0) >= 0.8
    )
    struggling = sum(
        1 for c in subjects.values()
        for info in c.values()
        if info.get("mastery", 0) < 0.5
    )

    lines.append(f"---\n**총 {total}개 개념** | 숙달: {mastered} | 취약: {struggling}")

    return "\n".join(lines)


def get_due_reviews_today(config: dict) -> str:
    """오늘 복습 예정인 개념 목록."""
    weak = _load_weak_concepts(config)
    display = _subject_display(config)
    today = datetime.now().strftime("%Y-%m-%d")

    due: list[dict] = []
    for subj_key, concepts in weak.items():
        for tag, info in concepts.items():
            next_review = info.get("sr_next_review")
            if next_review and next_review <= today:
                due.append({
                    "subject": display.get(subj_key, subj_key),
                    "subject_key": subj_key,
                    "tag": tag,
                    "mastery": info.get("mastery", 0),
                    "priority": info.get("priority", "?"),
                    "interval": info.get("sr_interval", "?"),
                })

    if not due:
        return "오늘 복습할 항목이 없습니다. 잘하고 있어요!"

    # priority 순 정렬
    priority_order = {"high": 0, "medium": 1, "low": 2}
    due.sort(key=lambda x: (priority_order.get(x["priority"], 3), x["mastery"]))

    lines = [f"## 오늘의 복습 ({today})", f"총 {len(due)}개 개념\n"]
    for d in due:
        icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(d["priority"], "⚪")
        lines.append(
            f"- {icon} **{d['tag']}** ({d['subject']}) — "
            f"mastery: {d['mastery']:.0%} | interval: {d['interval']}일"
        )

    return "\n".join(lines)
