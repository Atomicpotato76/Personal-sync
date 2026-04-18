#!/usr/bin/env python3
"""record_exam.py -- 실제 시험/모의고사 결과를 학습 메모리에 기록.

사용법:
  python record_exam.py add <과목> <개념태그> correct|wrong|partial [옵션]
         --source  exam|mock_exam   (기본: exam)
         --memo    "메모"
  python record_exam.py batch                               - 대화형 일괄 입력
  python record_exam.py deviation [<과목>]                  - 퀴즈 vs 시험 편차 리포트
  python record_exam.py postmortem <과목> [--exam-name "중간고사"]
                                                            - 대화형 사후 분석 세션
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from path_utils import apply_env_path_overrides

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"

sys.path.insert(0, str(SCRIPT_DIR))


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return apply_env_path_overrides(yaml.safe_load(f) or {})


def _parse_flag(argv: list[str], flag: str, default: str = "") -> str:
    if flag in argv:
        idx = argv.index(flag)
        if idx + 1 < len(argv) and not argv[idx + 1].startswith("--"):
            return argv[idx + 1]
    return default


def cmd_add(config: dict, subject: str, tag: str, result: str, source: str, memo: str) -> None:
    from memory_manager import MemoryManager

    if result not in ("correct", "wrong", "partial"):
        print(f"[ERROR] 결과는 correct, wrong, partial 중 하나여야 합니다: {result}")
        sys.exit(1)
    if source not in ("exam", "mock_exam"):
        print(f"[ERROR] source는 exam 또는 mock_exam이어야 합니다: {source}")
        sys.exit(1)

    mem = MemoryManager(config)
    mem.record_result(
        subject,
        [tag],
        result,
        memo=memo,
        source=source,
    )
    weight = mem._SOURCE_WEIGHTS[source]
    print(f"✓ 기록 완료: [{source} ×{weight}] {subject}/{tag} → {result}")
    if memo:
        print(f"  메모: {memo}")

    mastery = mem._weak_data.get(subject, {}).get(tag, {}).get("mastery", 0.0)
    print(f"  현재 마스터리: {mastery:.0%}")


def cmd_batch(config: dict) -> None:
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    subjects = list(config.get("subjects", {}).keys())
    if not subjects:
        print("[ERROR] config.yaml에 subjects가 없습니다.")
        sys.exit(1)

    print("\n=== 시험 결과 일괄 입력 (Enter로 완료) ===")
    print(f"과목 목록: {', '.join(subjects)}")

    while True:
        print()
        subject = input("과목 키 (Enter=종료): ").strip()
        if not subject:
            break
        if subject not in subjects:
            print(f"  [ERROR] 알 수 없는 과목: {subject}")
            continue

        concepts = list(mem._weak_data.get(subject, {}).keys())
        if concepts:
            print(f"  기존 개념: {', '.join(concepts[:10])}" + (" ..." if len(concepts) > 10 else ""))
        tag = input("  개념 태그: ").strip()
        if not tag:
            continue

        while True:
            result_raw = input("  결과 (c=correct, w=wrong, p=partial): ").strip().lower()
            if result_raw in ("c", "w", "p"):
                break
            print("  c, w, p 중 하나를 입력하세요.")
        result = {"c": "correct", "w": "wrong", "p": "partial"}[result_raw]

        source_raw = input("  출처 (1=exam, 2=mock_exam, Enter=exam): ").strip()
        source = "mock_exam" if source_raw == "2" else "exam"
        memo = input("  메모 (Enter=스킵): ").strip() or ""

        mem.record_result(subject, [tag], result, memo=memo, source=source)
        weight = mem._SOURCE_WEIGHTS[source]
        print(f"  → [{source} ×{weight}] {tag}: {result} 기록됨")

    print("\n일괄 입력 완료.")


def cmd_deviation(config: dict, subject_filter: str | None = None) -> None:
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    history = mem.get_history_snapshot()
    events = history.get("events", [])

    # 과목별, 개념별로 quiz vs exam 결과 분리
    from collections import defaultdict
    stats: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(lambda: defaultdict(lambda: {"quiz": [], "exam": []}))

    for ev in events:
        rec_source = ev.get("record_source", "quiz")
        if rec_source not in ("quiz", "exam", "mock_exam"):
            continue
        bucket = "exam" if rec_source in ("exam", "mock_exam") else "quiz"
        subj = ev.get("subject", "")
        if subject_filter and subj != subject_filter:
            continue
        result = ev.get("result", "")
        score = 1.0 if result == "correct" else 0.5 if result == "partial" else 0.0
        for concept in ev.get("concepts", []):
            stats[subj][concept][bucket].append(score)

    has_output = False
    for subj, concepts in sorted(stats.items()):
        concept_rows = []
        for tag, buckets in concepts.items():
            q_scores = buckets["quiz"]
            e_scores = buckets["exam"]
            if not q_scores or not e_scores:
                continue
            q_avg = sum(q_scores) / len(q_scores)
            e_avg = sum(e_scores) / len(e_scores)
            deviation = e_avg - q_avg
            concept_rows.append((tag, q_avg, e_avg, deviation, len(q_scores), len(e_scores)))

        if not concept_rows:
            continue

        has_output = True
        print(f"\n{'='*55}")
        print(f"  과목: {subj}")
        print(f"{'='*55}")
        print(f"  {'개념':<25} {'퀴즈':>6} {'시험':>6} {'편차':>7} {'퀴즈n':>5} {'시험n':>5}")
        print(f"  {'-'*25} {'------':>6} {'------':>6} {'-------':>7} {'-----':>5} {'-----':>5}")

        concept_rows.sort(key=lambda x: x[3])  # 편차 낮은 순
        for tag, q_avg, e_avg, deviation, qn, en in concept_rows:
            arrow = "▼" if deviation < -0.1 else ("▲" if deviation > 0.1 else " ")
            print(
                f"  {tag:<25} {q_avg:>5.0%} {e_avg:>6.0%} "
                f" {arrow}{deviation:+.0%}  {qn:>5} {en:>5}"
            )

    if not has_output:
        print("퀴즈와 시험 결과를 모두 가진 개념이 없습니다.")
        print("먼저 시험 결과를 기록하세요: python record_exam.py add <과목> <태그> correct")


def cmd_postmortem(config: dict, subject: str, exam_name: str = "") -> None:
    """대화형으로 시험 오답을 입력받고, 끝나면 약점 TOP 3 요약 + hermes 갱신."""
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    name = exam_name or ""

    print(f"\n=== 시험 사후 분석 [{subject}{'  ' + name if name else ''}] ===")
    print("틀린 문항을 하나씩 입력하세요. 빈 입력으로 종료합니다.\n")

    error_map = {"1": "knowledge_gap", "2": "confusion", "3": "careless", "4": "misread"}
    recorded = 0

    while True:
        tag = input("개념 태그 (Enter=종료): ").strip()
        if not tag:
            break

        while True:
            result_raw = input("  결과 (w=wrong, p=partial, c=correct, Enter=wrong): ").strip().lower() or "w"
            if result_raw in ("w", "p", "c"):
                break
            print("  w, p, c 중 하나를 입력하세요.")
        result = {"w": "wrong", "p": "partial", "c": "correct"}[result_raw]

        print("  오답 원인: 1=지식부족  2=혼동  3=실수  4=문제오독  Enter=스킵")
        ec_raw = input("  원인 번호: ").strip()
        error_category = error_map.get(ec_raw)

        memo = input("  메모 (Enter=스킵): ").strip() or ""

        mem.record_result(
            subject,
            [tag],
            result,
            memo=memo,
            error_category=error_category,
            source="exam",
        )
        recorded += 1
        print(f"  → 기록 완료: {tag} ({result})")

    if recorded == 0:
        print("입력된 문항이 없습니다.")
        return

    print(f"\n총 {recorded}개 문항 입력 완료.")

    # 약점 요약 출력
    summary = mem.get_postmortem_summary(subject, exam_name=name or None)
    _print_postmortem_summary(summary)

    # Hermes 일정 갱신
    try:
        from agents.hermes_agent import HermesAgent
        agent = HermesAgent(config)
        agent.refresh_from_event("exam_postmortem")
        print("\n[Hermes] 다음 주 계획이 갱신되었습니다.")
    except Exception as e:
        print(f"\n[경고] Hermes 갱신 실패: {e}")


def _print_postmortem_summary(summary: dict) -> None:
    subject = summary.get("subject", "")
    exam_name = summary.get("exam_name") or ""
    total = summary.get("total_exam_events", 0)
    top_weak = summary.get("top_weak", [])
    error_dist = summary.get("error_distribution", {})
    recommended = summary.get("recommended_focus", [])

    title = f"[{subject}{'  ' + exam_name if exam_name else ''}]  시험 사후 분석"
    print(f"\n{'=' * 55}")
    print(f"  {title}")
    print(f"  총 시험 이벤트: {total}건")
    print(f"{'=' * 55}")

    if top_weak:
        print("\n  ■ 취약 개념 TOP (시험 평균 정답률 낮은 순)")
        for i, item in enumerate(recommended, 1):
            print(
                f"  {i}. {item['concept']:<25}"
                f"  시험정답률: {item['exam_avg']:.0%}"
                f"  현재마스터리: {item['current_mastery']:.0%}"
            )
    else:
        print("\n  시험 데이터가 없거나 집계할 개념이 없습니다.")

    total_errors = sum(error_dist.values())
    if total_errors > 0:
        label_map = {
            "knowledge_gap": "지식 부족",
            "confusion": "개념 혼동",
            "careless": "실수",
            "misread": "문제 오독",
        }
        print("\n  ■ 오답 원인 분포")
        for cat, count in sorted(error_dist.items(), key=lambda x: -x[1]):
            if count == 0:
                continue
            bar = "█" * count
            print(f"  {label_map.get(cat, cat):<12} {bar} ({count})")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    config = load_config()
    cmd = sys.argv[1]

    if cmd == "add":
        if len(sys.argv) < 5:
            print("사용법: python record_exam.py add <과목> <태그> correct|wrong|partial [--source exam|mock_exam] [--memo '메모']")
            sys.exit(1)
        subject = sys.argv[2]
        tag = sys.argv[3]
        result = sys.argv[4]
        source = _parse_flag(sys.argv, "--source", "exam")
        memo = _parse_flag(sys.argv, "--memo", "")
        cmd_add(config, subject, tag, result, source, memo)

    elif cmd == "batch":
        cmd_batch(config)

    elif cmd == "deviation":
        subject_filter = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_deviation(config, subject_filter)

    elif cmd == "postmortem":
        if len(sys.argv) < 3:
            print("사용법: python record_exam.py postmortem <과목> [--exam-name '시험명']")
            sys.exit(1)
        subject = sys.argv[2]
        exam_name = _parse_flag(sys.argv, "--exam-name", "")
        cmd_postmortem(config, subject, exam_name)

    else:
        print(f"[ERROR] 알 수 없는 명령: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
