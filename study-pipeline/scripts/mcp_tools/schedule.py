"""schedule.py -- Hermes 일정 관리 MCP 도구."""
from __future__ import annotations

from datetime import date, timedelta

from agents.hermes_agent import HermesAgent
from hermes_store import HermesStore


def _subject_display(config: dict) -> dict[str, str]:
    mapping = config.get("folder_mapping", {})
    return {v: k for k, v in mapping.items()}


def _format_plan(plan: dict, config: dict) -> str:
    if not plan:
        return "아직 생성된 Hermes 일정이 없습니다."

    display = _subject_display(config)
    lines = [
        f"## Hermes {plan.get('scope', 'schedule')} plan",
        f"- 기간: {plan.get('start_date', '?')} ~ {plan.get('end_date', '?')}",
        f"- 생성 시각: {plan.get('generated_at', '-')}",
        f"- 요약: {plan.get('summary', '-')}",
        "",
    ]

    blocks = plan.get("blocks", [])
    if blocks:
        lines.append("### 배치된 학습 블록")
        for block in blocks:
            subject_name = display.get(block.get("subject", ""), block.get("subject_display", block.get("subject", "")))
            focus = ", ".join(block.get("focus", []))
            lines.append(
                f"- {block.get('date', '?')} {block.get('start', '?')}-{block.get('end', '?')} | "
                f"{subject_name} | {block.get('title', '?')} | {block.get('reason', '')}"
            )
            if focus:
                lines.append(f"  focus: {focus}")
        lines.append("")
    else:
        lines.append("배치된 학습 블록이 없습니다.\n")

    backlog = plan.get("backlog", [])
    if backlog:
        lines.append(f"### 미배치 후보 ({len(backlog)}개)")
        for item in backlog[:5]:
            subject_name = display.get(item.get("subject", ""), item.get("subject_display", item.get("subject", "")))
            lines.append(f"- {subject_name} | {item.get('title', '?')} | {item.get('reason', '')}")
        lines.append("")

    events = plan.get("upcoming_events", [])
    if events:
        lines.append("### 다가오는 일정")
        for event in events[:5]:
            subject_name = display.get(event.get("subject", ""), event.get("subject", ""))
            lines.append(f"- {event.get('date', '?')} | {subject_name} | {event.get('title', '?')} ({event.get('days_left', '?')}일 남음)")

    return "\n".join(lines)


def get_schedule(period: str, anchor_date: str, config: dict) -> str:
    agent = HermesAgent(config)
    normalized = "week" if period == "week" else "day"
    plan = agent.get_schedule(normalized, anchor_date, auto_create=True)
    return _format_plan(plan, config)


def plan_week(anchor_date: str, config: dict) -> str:
    agent = HermesAgent(config)
    plan = agent.plan_week(anchor_date or None, reason="mcp_plan_week")
    return _format_plan(plan, config)


def reschedule_schedule(period: str, anchor_date: str, config: dict) -> str:
    agent = HermesAgent(config)
    normalized = "week" if period == "week" else "day"
    plan = agent.reschedule(normalized, anchor_date or None, reason="mcp_reschedule")
    return _format_plan(plan, config)


def add_exam_or_deadline(
    subject: str,
    when: str,
    title: str,
    details: str,
    kind: str,
    config: dict,
) -> str:
    if subject not in config.get("subjects", {}):
        return f"알 수 없는 subject입니다: {subject}"

    try:
        date.fromisoformat(when)
    except ValueError:
        return f"날짜 형식이 올바르지 않습니다: {when} (YYYY-MM-DD 사용)"

    normalized_kind = "deadline" if kind == "deadline" else "exam"
    store = HermesStore(config)
    event = store.add_event(subject, title, when, details=details, kind=normalized_kind)

    agent = HermesAgent(config)
    anchor = when if normalized_kind == "exam" else None
    week_plan = agent.plan_week(anchor, reason=f"mcp_{normalized_kind}_added")

    subject_name = _subject_display(config).get(subject, subject)
    lines = [
        f"일정 추가 완료: {event['date']} | {subject_name} | {event['title']} ({event['kind']})",
        "",
        _format_plan(week_plan, config),
    ]
    return "\n".join(lines)

