#!/usr/bin/env python3
"""review.py -- 퀴즈 검토, 결과 기록, 취약 개념 리포트."""

from __future__ import annotations

import io
import sys
from datetime import datetime
from pathlib import Path

# Windows 콘솔 UTF-8 출력 보장
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stdin.encoding != "utf-8":
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")

import yaml

from memory_manager import MemoryManager
from path_utils import get_study_paths
from quiz_store import approve_quiz, find_quiz_json, load_quiz_json, save_quiz_json

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[ERROR] config.yaml을 찾을 수 없습니다: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def refresh_hermes(config: dict, reason: str) -> None:
    try:
        from agents.hermes_agent import HermesAgent

        HermesAgent(config).refresh_from_event(reason)
        print("→ Hermes 일정 갱신 완료")
    except Exception as e:
        print(f"[WARN] Hermes 일정 갱신 실패: {e}")


_ERROR_CATEGORIES = {
    "1": "knowledge_gap",
    "2": "confusion",
    "3": "careless",
    "4": "misread",
}


def _ask_confidence() -> int | None:
    """답 공개 전 신뢰도 1-5 입력. Enter로 스킵 → None."""
    raw = input("신뢰도 (1=전혀모름 ~ 5=확실, Enter로 스킵): ").strip()
    if not raw:
        return None
    if raw in ("1", "2", "3", "4", "5"):
        return int(raw)
    return None


def _ask_item_quality() -> int | None:
    """문항 품질 1-5 입력. Enter로 스킵 → None."""
    raw = input("문항 품질 (1=매우나쁨 ~ 5=완벽, Enter로 스킵): ").strip()
    if raw in ("1", "2", "3", "4", "5"):
        return int(raw)
    return None


def _ask_error_category() -> str | None:
    """오답 원인 분류 선택. Enter로 스킵 → None."""
    print("  오답 원인:")
    print("    1. knowledge_gap  — 아직 배우지 않은 개념")
    print("    2. confusion      — 비슷한 개념과 혼동")
    print("    3. careless       — 계산/주의 실수")
    print("    4. misread        — 문제 오독")
    raw = input("  선택 (1-4, Enter로 스킵): ").strip()
    return _ERROR_CATEGORIES.get(raw)


def cmd_list(config: dict) -> None:
    paths = get_study_paths(config)
    if not paths.queue.exists():
        print("queue/ 디렉토리가 없습니다.")
        return

    json_files = sorted(paths.queue.glob("*.json"))
    if not json_files:
        print("queue/에 항목이 없습니다.")
        return

    print(f"queue/ 항목: {len(json_files)}개\n")
    for jf in json_files:
        data = load_quiz_json(jf)
        if data is None:
            print(f"[WARN] 퀴즈 파일 읽기 실패: {jf.name}")
            continue

        for item in data.get("items", []):
            q_preview = item.get("question", "")[:70]
            tags = ", ".join(item.get("concept_tags", []))
            diff = item.get("difficulty", "?")
            print(f"  [{diff}] {data['id']}")
            print(f"    Q: {q_preview}")
            print(f"    tags: {tags}")
            print()


def cmd_do(config: dict) -> None:
    paths = get_study_paths(config)
    paths.approved.mkdir(parents=True, exist_ok=True)

    if not paths.queue.exists():
        print("queue/ 디렉토리가 없습니다.")
        return

    json_files = sorted(paths.queue.glob("*.json"))
    if not json_files:
        print("queue/에 항목이 없습니다.")
        return

    memory = MemoryManager(config)

    for jf in json_files:
        data = load_quiz_json(jf)
        if data is None:
            print(f"[WARN] 퀴즈 파일 읽기 실패: {jf.name}")
            continue

        quiz_id = data["id"]
        subject = data.get("subject", "unknown")
        source_note = data.get("source_note", "")
        items = data.get("items", [])
        skipped = False

        print(f"\n{'='*60}")
        print(f"Quiz: {quiz_id}")
        print(f"Subject: {subject} | Source: {source_note}")
        print(f"{'='*60}")

        for i, item in enumerate(items):
            q_num = i + 1
            diff = item.get("difficulty", "?")
            q_type = item.get("type", "")
            question = item.get("question", "")
            tags = item.get("concept_tags", [])

            print(f"\n--- Q{q_num} [{diff}] {q_type} ---")
            print(f"\n{question}\n")

            # 1.2: 답 공개 전 신뢰도 입력 (Enter로 스킵)
            confidence = _ask_confidence()

            input("(답을 생각한 후 Enter를 누르세요...)")

            print("\n[Expected Answer Keys]")
            for key in item.get("expected_answer_keys", []):
                print(f"  ✓ {key}")

            while True:
                result_input = input(
                    "\n결과: c(correct) / w(wrong) / p(partial) / s(skip): "
                ).strip().lower()
                if result_input in ("c", "w", "p", "s"):
                    break
                print("c, w, p, s 중 하나를 입력하세요.")

            if result_input == "s":
                skipped = True
                print("→ 이 퀴즈를 건너뜁니다.")
                break

            result = {"c": "correct", "w": "wrong", "p": "partial"}[result_input]
            memo = None
            error_category = None

            if result in ("wrong", "partial"):
                memo = input("오답 메모 (Enter로 스킵): ").strip() or None
                # 1.3: wrong일 때 오류 분류
                if result == "wrong":
                    error_category = _ask_error_category()

            # 2.5: 문항 품질 평가
            item_quality = _ask_item_quality()

            now = datetime.now().isoformat(timespec="seconds")
            item["review"] = {
                "result": result,
                "memo": memo,
                "reviewed_at": now,
                "confidence": confidence,
                "error_category": error_category,
                "item_quality": item_quality,
            }
            memory.record_result(
                subject, tags, result,
                source_note=source_note,
                memo=memo or "",
                confidence=confidence,
                error_category=error_category,
            )

        if skipped:
            save_quiz_json(jf, data)
            print(f"\n→ {quiz_id}: queue에 유지됨 (skip)")
            continue

        approve_quiz(config, quiz_id, data=data)
        print(f"\n→ {quiz_id}: approved/로 이동 완료")

    print("\n완료. weak_concepts.json 갱신됨.")
    refresh_hermes(config, "review_completed")


def cmd_report(config: dict) -> None:
    memory = MemoryManager(config)
    weak = memory.get_weak_snapshot()
    history = memory.get_history_snapshot()

    if not weak:
        print("취약 개념 데이터가 없습니다. 먼저 review를 진행하세요.")
        return

    for subject, concepts in sorted(weak.items()):
        print(f"\n{'='*50}")
        print(f"  과목: {subject}")
        print(f"{'='*50}")

        sorted_concepts = sorted(
            concepts.items(), key=lambda x: x[1].get("mastery", 0)
        )

        for tag, info in sorted_concepts:
            mastery = info.get("mastery", 0)
            priority = info.get("priority", "?")
            encounter = info.get("encounter_count", 0)
            correct = info.get("correct_count", 0)

            bar_len = 20
            filled = int(mastery * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)

            priority_marker = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                priority, "?"
            )

            print(
                f"\n  {priority_marker} {tag}"
                f"\n    [{bar}] {mastery:.0%}  ({correct}/{encounter})"
            )

            mistakes = info.get("recent_mistakes", [])
            if mistakes:
                last = mistakes[-1]
                print(
                    f"    최근 실수: {last['date'][:10]} ({last['result']})"
                    + (f" — {last['memo']}" if last.get("memo") else "")
                )
                # 1.3: 오류 분류 분포
                categories = [m.get("error_category") for m in mistakes if m.get("error_category")]
                if categories:
                    from collections import Counter
                    dist = Counter(categories)
                    parts = "  |  ".join(f"{k}: {v}" for k, v in dist.most_common())
                    print(f"    오류 분류: {parts}")

    # 1.2: Calibration 커브 섹션
    _print_calibration_report(history)

    print()


def _print_calibration_report(history: dict) -> None:
    """신뢰도(1-5)별 정답률 ASCII 바 차트 출력."""
    events = history.get("events", [])
    confidence_events = [e for e in events if e.get("confidence") is not None]
    if not confidence_events:
        return

    from collections import defaultdict
    buckets: dict[int, list[int]] = defaultdict(list)
    for e in confidence_events:
        c = e["confidence"]
        correct = 1 if e["result"] == "correct" else (0.5 if e["result"] == "partial" else 0)
        buckets[c].append(correct)

    print(f"\n{'─'*50}")
    print("  [신뢰도 캘리브레이션] 신뢰도별 실제 정답률")
    print(f"{'─'*50}")
    bar_len = 20
    for level in range(1, 6):
        vals = buckets.get(level, [])
        if not vals:
            print(f"  {level}점: (데이터 없음)")
            continue
        accuracy = sum(vals) / len(vals)
        filled = int(accuracy * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"  {level}점: [{bar}] {accuracy:.0%}  (n={len(vals)})")


def cmd_update(config: dict, quiz_id: str, result: str, memo: str | None) -> None:
    if result not in ("correct", "wrong", "partial"):
        print(f"[ERROR] 결과는 correct, wrong, partial 중 하나여야 합니다: {result}")
        sys.exit(1)

    json_path = find_quiz_json(config, quiz_id)
    if json_path is None:
        print(f"[ERROR] ID를 찾을 수 없습니다: {quiz_id}")
        sys.exit(1)

    data = load_quiz_json(json_path)
    if data is None:
        print(f"[ERROR] 퀴즈 파일을 읽을 수 없습니다: {json_path.name}")
        sys.exit(1)

    memory = MemoryManager(config)
    now = datetime.now().isoformat(timespec="seconds")
    subject = data.get("subject", "unknown")
    source_note = data.get("source_note", "")

    for item in data.get("items", []):
        item["review"] = {
            "result": result,
            "memo": memo,
            "reviewed_at": now,
        }
        memory.record_result(
            subject,
            item.get("concept_tags", []),
            result,
            source_note=source_note,
            memo=memo or "",
        )

    save_quiz_json(json_path, data)
    if json_path.parent == get_study_paths(config).queue:
        approve_quiz(config, quiz_id, data=data)

    refresh_hermes(config, "review_updated")
    print(f"→ {quiz_id}: 모든 항목을 '{result}'로 업데이트 완료")


def cmd_exam_deviation(config: dict, subject_filter: str | None = None) -> None:
    """퀴즈 vs 실제 시험 편차 리포트 (2.4)."""
    try:
        from record_exam import cmd_deviation
        cmd_deviation(config, subject_filter)
    except ImportError:
        print("[ERROR] record_exam.py를 불러올 수 없습니다.")


def cmd_postmortem_report(config: dict, subject_filter: str | None = None) -> None:
    """시험 사후 분석 리포트 출력 (3.4)."""
    from memory_manager import MemoryManager
    from exam_postmortem import _print_summary

    mem = MemoryManager(config)
    subjects = [subject_filter] if subject_filter else list(config.get("subjects", {}).keys())

    if not subjects:
        print("[ERROR] config.yaml에 subjects가 없습니다.")
        return

    for subj in subjects:
        summary = mem.get_postmortem_summary(subj)
        _print_summary(summary)


def main() -> None:
    if len(sys.argv) < 2:
        print("사용법:")
        print("  python review.py list                              - queue 목록 출력")
        print("  python review.py do                                - interactive 풀기")
        print("  python review.py report                            - 취약 개념 리포트")
        print("  python review.py report --exam-deviation [<과목>]  - 퀴즈 vs 시험 편차")
        print("  python review.py report --postmortem [<과목>]      - 시험 사후 분석")
        print("  python review.py update <id> correct|wrong|partial [메모]")
        sys.exit(0)

    config = load_config()
    cmd = sys.argv[1]

    if cmd == "list":
        cmd_list(config)
    elif cmd == "do":
        cmd_do(config)
    elif cmd == "report":
        if "--exam-deviation" in sys.argv:
            subject_filter = sys.argv[sys.argv.index("--exam-deviation") + 1] if sys.argv.index("--exam-deviation") + 1 < len(sys.argv) and not sys.argv[sys.argv.index("--exam-deviation") + 1].startswith("--") else None
            cmd_exam_deviation(config, subject_filter)
        elif "--postmortem" in sys.argv:
            idx = sys.argv.index("--postmortem")
            subject_filter = (
                sys.argv[idx + 1]
                if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--")
                else None
            )
            cmd_postmortem_report(config, subject_filter)
        else:
            cmd_report(config)
    elif cmd == "update":
        if len(sys.argv) < 4:
            print("사용법: python review.py update <id> correct|wrong|partial [메모]")
            sys.exit(1)
        quiz_id = sys.argv[2]
        result = sys.argv[3]
        memo = " ".join(sys.argv[4:]) if len(sys.argv) > 4 else None
        cmd_update(config, quiz_id, result, memo)
    else:
        print(f"[ERROR] 알 수 없는 명령: {cmd}")
        print("사용 가능한 명령: list, do, report, update")
        sys.exit(1)


if __name__ == "__main__":
    main()
