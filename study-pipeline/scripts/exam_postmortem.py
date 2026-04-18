#!/usr/bin/env python3
"""exam_postmortem.py -- 시험 사후 분석 세션 CLI.

사용법:
  python exam_postmortem.py start <과목> [<시험명>]   - 사후 분석 세션 시작
  python exam_postmortem.py report [<과목>]          - 분석 결과 리포트
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"

sys.path.insert(0, str(SCRIPT_DIR))


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _print_summary(summary: dict) -> None:
    subject = summary.get("subject", "")
    exam_name = summary.get("exam_name") or ""
    total = summary.get("total_exam_events", 0)
    recommended = summary.get("recommended_focus", [])
    error_dist = summary.get("error_distribution", {})

    title = f"[{subject}{'  ' + exam_name if exam_name else ''}]  시험 사후 분석 리포트"
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"  총 시험 이벤트 수: {total}건")
    print(f"{'=' * 60}")

    if recommended:
        print("\n  ■ 취약 개념 순위 (시험 정답률 낮은 순)")
        for i, item in enumerate(recommended, 1):
            exam_pct = f"{item['exam_avg']:.0%}"
            curr_pct = f"{item['current_mastery']:.0%}"
            print(f"  {i}. {item['concept']:<28} 시험: {exam_pct:>5}  현재: {curr_pct:>5}")
    else:
        print("\n  집계할 시험 데이터가 없습니다.")
        print("  먼저 'start' 명령으로 시험 결과를 입력하세요.")
        return

    total_errors = sum(error_dist.values())
    if total_errors > 0:
        label_map = {
            "knowledge_gap": "지식 부족",
            "confusion":     "개념 혼동",
            "careless":      "실수",
            "misread":       "문제 오독",
        }
        print("\n  ■ 오답 원인 분포")
        for cat, count in sorted(error_dist.items(), key=lambda x: -x[1]):
            if count == 0:
                continue
            bar = "█" * min(count, 20)
            print(f"  {label_map.get(cat, cat):<12}  {bar} ({count})")

    if recommended:
        print("\n  ■ 다음 주 추천 집중 개념")
        for item in recommended[:3]:
            print(f"    → {item['concept']}  (현재 마스터리 {item['current_mastery']:.0%})")
    print()


def cmd_start(config: dict, subject: str, exam_name: str = "") -> None:
    """대화형으로 시험 오답을 입력받고 분석 결과를 출력."""
    from record_exam import cmd_postmortem
    cmd_postmortem(config, subject, exam_name)


def cmd_report(config: dict, subject: str | None = None) -> None:
    """저장된 시험 이벤트를 집계해 사후 분석 리포트 출력."""
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    subjects = [subject] if subject else list(config.get("subjects", {}).keys())

    if not subjects:
        print("[ERROR] config.yaml에 subjects가 없습니다.")
        sys.exit(1)

    for subj in subjects:
        summary = mem.get_postmortem_summary(subj)
        _print_summary(summary)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    config = load_config()
    cmd = sys.argv[1]

    if cmd == "start":
        if len(sys.argv) < 3:
            print("사용법: python exam_postmortem.py start <과목> [<시험명>]")
            sys.exit(1)
        subject = sys.argv[2]
        exam_name = sys.argv[3] if len(sys.argv) > 3 else ""
        cmd_start(config, subject, exam_name)

    elif cmd == "report":
        subject = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_report(config, subject)

    else:
        print(f"[ERROR] 알 수 없는 명령: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
