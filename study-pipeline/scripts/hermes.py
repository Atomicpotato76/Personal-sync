#!/usr/bin/env python3
"""hermes.py -- Hermes 일정 관리 CLI."""

from __future__ import annotations

import io
import sys
from datetime import date, timedelta
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import yaml

from agents.hermes_agent import HermesAgent
from hermes_store import HermesStore

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def print_plan(plan: dict) -> None:
    if not plan:
        print("계획이 없습니다.")
        return

    print(f"[{plan['scope']}] {plan['start_date']} ~ {plan['end_date']}")
    print(plan.get("summary", ""))
    print()

    blocks = plan.get("blocks", [])
    if not blocks:
        print("배치된 블록이 없습니다.")
    else:
        print("배치된 학습 블록:")
        for block in blocks:
            focus = ", ".join(block.get("focus", []))
            print(
                f"  - {block['date']} {block['start']}-{block['end']} | "
                f"{block['subject_display']} | {block['title']} | {block['reason']}"
            )
            if focus:
                print(f"    focus: {focus}")

    backlog = plan.get("backlog", [])
    if backlog:
        print()
        print(f"미배치 후보: {len(backlog)}개")
        for item in backlog[:5]:
            print(f"  - {item['subject_display']} | {item['title']} | {item['reason']}")


def cmd_status(config: dict) -> None:
    store = HermesStore(config)
    state = store.load_state()
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    today_plan = store.get_day_plan(today.isoformat())
    week_plan = store.get_week_plan(week_start.isoformat())
    events = store.upcoming_events(within_days=21)

    print("=== Hermes Status ===")
    print(f"last_generated: {state.get('last_generated') or '-'}")
    print(f"last_reason: {state.get('last_reason') or '-'}")
    print(f"today_blocks: {len((today_plan or {}).get('blocks', []))}")
    print(f"week_blocks: {len((week_plan or {}).get('blocks', []))}")
    print(f"upcoming_events: {len(events)}")
    if events:
        for event in events[:5]:
            print(f"  - {event['date']} | {event['subject']} | {event['title']} ({event['days_left']}일 남음)")


def main() -> None:
    config = load_config()
    agent = HermesAgent(config)
    store = HermesStore(config)

    if len(sys.argv) < 2:
        print("사용법:")
        print("  python hermes.py plan-day [YYYY-MM-DD]")
        print("  python hermes.py plan-week [YYYY-MM-DD]")
        print("  python hermes.py reschedule [day|week] [YYYY-MM-DD]")
        print("  python hermes.py status")
        print("  python hermes.py add-exam <subject> <YYYY-MM-DD> <title>")
        print("  python hermes.py add-deadline <subject> <YYYY-MM-DD> <title>")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "plan-day":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        print_plan(agent.plan_day(target, reason="cli_plan_day"))
    elif cmd == "plan-week":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        print_plan(agent.plan_week(target, reason="cli_plan_week"))
    elif cmd == "reschedule":
        period = sys.argv[2] if len(sys.argv) > 2 else "day"
        target = sys.argv[3] if len(sys.argv) > 3 else None
        print_plan(agent.reschedule(period, target, reason="cli_reschedule"))
    elif cmd == "status":
        cmd_status(config)
    elif cmd in {"add-exam", "add-deadline"}:
        if len(sys.argv) < 5:
            print(f"사용법: python hermes.py {cmd} <subject> <YYYY-MM-DD> <title>")
            sys.exit(1)
        subject = sys.argv[2]
        when = sys.argv[3]
        title = " ".join(sys.argv[4:])
        kind = "deadline" if cmd == "add-deadline" else "exam"
        event = store.add_event(subject, title, when, kind=kind)
        print(f"추가 완료: {event['date']} | {event['subject']} | {event['title']} ({event['kind']})")
        print()
        print_plan(agent.plan_week(reason=f"{kind}_added"))
    else:
        print(f"[ERROR] 알 수 없는 명령: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
