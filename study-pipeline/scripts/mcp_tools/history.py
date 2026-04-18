"""history.py -- 퀴즈 이력 조회 MCP 도구."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from path_utils import get_study_paths


def _load_learning_history(config: dict) -> dict:
    paths = get_study_paths(config)
    path = paths.cache / "learning_history.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _subject_display(config: dict) -> dict[str, str]:
    mapping = config.get("folder_mapping", {})
    return {v: k for k, v in mapping.items()}


def get_quiz_history(subject: str, concept_tag: str, config: dict) -> str:
    """퀴즈 풀이 이력 조회."""
    history = _load_learning_history(config)
    display = _subject_display(config)
    events = history.get("events", [])

    if not events:
        return "퀴즈 풀이 이력이 없습니다."

    # 필터링
    filtered = events
    if subject:
        filtered = [e for e in filtered if e.get("subject") == subject]
    if concept_tag:
        filtered = [
            e for e in filtered
            if concept_tag.lower() in " ".join(e.get("concepts", [])).lower()
        ]

    if not filtered:
        filter_desc = f"subject={subject}" if subject else ""
        if concept_tag:
            filter_desc += f" concept={concept_tag}" if filter_desc else f"concept={concept_tag}"
        return f"조건에 맞는 이력이 없습니다. (필터: {filter_desc})"

    # 통계 계산
    total = len(filtered)
    correct = sum(1 for e in filtered if e.get("result") == "correct")
    wrong = sum(1 for e in filtered if e.get("result") == "wrong")
    partial = sum(1 for e in filtered if e.get("result") == "partial")

    # 과목별 통계
    by_subject: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0, "wrong": 0})
    for e in filtered:
        s = e.get("subject", "unknown")
        by_subject[s]["total"] += 1
        r = e.get("result", "")
        if r in by_subject[s]:
            by_subject[s][r] += 1

    # 개념별 통계
    by_concept: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0, "wrong": 0, "memos": []})
    for e in filtered:
        for c in e.get("concepts", []):
            by_concept[c]["total"] += 1
            r = e.get("result", "")
            if r in by_concept[c]:
                by_concept[c][r] += 1
            memo = e.get("memo", "")
            if memo and r == "wrong":
                by_concept[c]["memos"].append(memo)

    lines = ["## 퀴즈 이력\n"]
    lines.append(f"총 {total}회 | 정답: {correct} | 오답: {wrong} | 부분: {partial}")
    if total > 0:
        lines.append(f"정답률: **{correct/total:.0%}**\n")

    # 과목별
    if len(by_subject) > 1 or not subject:
        lines.append("### 과목별")
        for s, stats in sorted(by_subject.items()):
            name = display.get(s, s)
            rate = stats["correct"] / max(stats["total"], 1)
            lines.append(f"- {name}: {stats['correct']}/{stats['total']} ({rate:.0%})")
        lines.append("")

    # 취약 개념 (오답률 높은 순)
    weak_concepts = sorted(
        by_concept.items(),
        key=lambda x: x[1]["wrong"] / max(x[1]["total"], 1),
        reverse=True,
    )
    if weak_concepts:
        lines.append("### 취약 개념 (오답률 순)")
        for tag, stats in weak_concepts[:10]:
            rate = stats["wrong"] / max(stats["total"], 1)
            lines.append(f"- **{tag}** — 오답률: {rate:.0%} ({stats['wrong']}/{stats['total']})")
            for memo in stats["memos"][-2:]:  # 최근 오답 메모 2개
                lines.append(f"  - {memo[:100]}")
        lines.append("")

    # 최근 이벤트
    recent = sorted(filtered, key=lambda e: e.get("timestamp", ""), reverse=True)[:5]
    lines.append("### 최근 풀이")
    for e in recent:
        ts = e.get("timestamp", "?")[:16]
        subj = display.get(e.get("subject", ""), e.get("subject", ""))
        result = {"correct": "✅", "wrong": "❌", "partial": "🟡"}.get(e.get("result", ""), "?")
        concepts = ", ".join(e.get("concepts", []))
        lines.append(f"- {ts} | {result} {subj} | {concepts}")

    return "\n".join(lines)


def get_weekly_summary(config: dict) -> str:
    """이번 주 학습 통계 요약."""
    history = _load_learning_history(config)
    display = _subject_display(config)
    events = history.get("events", [])

    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    week_start_str = week_start.strftime("%Y-%m-%d")

    weekly = [
        e for e in events
        if e.get("timestamp", "")[:10] >= week_start_str
    ]

    total = len(weekly)
    correct = sum(1 for e in weekly if e.get("result") == "correct")
    wrong = sum(1 for e in weekly if e.get("result") == "wrong")

    # 일별 분포
    by_day: dict[str, int] = defaultdict(int)
    for e in weekly:
        day = e.get("timestamp", "?")[:10]
        by_day[day] += 1

    # 과목별
    by_subject: dict[str, int] = defaultdict(int)
    for e in weekly:
        by_subject[e.get("subject", "unknown")] += 1

    lines = [f"## 이번 주 학습 요약 ({week_start_str} ~)\n"]

    if total == 0:
        lines.append("이번 주 아직 퀴즈를 풀지 않았습니다.")
        return "\n".join(lines)

    lines.append(f"**총 {total}회** | 정답: {correct} | 오답: {wrong} | 정답률: {correct/max(total,1):.0%}\n")

    lines.append("### 일별")
    for day in sorted(by_day.keys()):
        lines.append(f"- {day}: {by_day[day]}회")

    lines.append("\n### 과목별")
    for s, count in sorted(by_subject.items(), key=lambda x: -x[1]):
        name = display.get(s, s)
        lines.append(f"- {name}: {count}회")

    # 연속 학습 일수
    study_days = sorted(by_day.keys())
    streak = len(study_days)
    lines.append(f"\n**이번 주 학습 일수: {streak}일**")

    return "\n".join(lines)
