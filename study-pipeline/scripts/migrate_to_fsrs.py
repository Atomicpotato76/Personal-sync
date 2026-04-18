#!/usr/bin/env python3
"""migrate_to_fsrs.py -- SM-2 weak_concepts.json → FSRS 초기 카드 상태 변환.

사용법:
  python scripts/migrate_to_fsrs.py [--dry-run] [--enable]

  --dry-run   실제 파일 수정 없이 변환 결과만 출력
  --enable    마이그레이션 완료 후 config.yaml의 scheduler를 fsrs로 설정

변환 규칙:
  stability  ≈ sr_interval (수렴 시 stability ≈ interval)
  difficulty = clamp(1 + (1 - mastery) * 9, 1, 10)  (mastery 역비례)
  due        = sr_next_review (없으면 오늘)
  state      = Review (2)  — 기존 SM-2 데이터는 모두 Review 상태로 취급
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from path_utils import get_study_paths, apply_env_path_overrides

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"

try:
    from fsrs import Card, Scheduler, State as FsrsState
    _FSRS_AVAILABLE = True
except ImportError:
    _FSRS_AVAILABLE = False


def load_config() -> dict:
    import yaml
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return apply_env_path_overrides(yaml.safe_load(f) or {})


def load_weak(pipeline_dir: Path) -> dict:
    weak_path = pipeline_dir / "weak_concepts.json"
    if not weak_path.exists():
        print(f"[ERROR] weak_concepts.json 없음: {weak_path}")
        sys.exit(1)
    with open(weak_path, encoding="utf-8") as f:
        return json.load(f)


def save_weak(pipeline_dir: Path, data: dict) -> None:
    weak_path = pipeline_dir / "weak_concepts.json"
    with open(weak_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def backup_weak(pipeline_dir: Path) -> Path:
    weak_path = pipeline_dir / "weak_concepts.json"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = pipeline_dir / f"weak_concepts.pre-fsrs.{ts}.json"
    import shutil
    shutil.copy2(weak_path, backup_path)
    return backup_path


def _card_to_dict(card: "Card") -> dict:
    return {
        "card_id": card.card_id,
        "state": card.state.value,
        "step": card.step,
        "stability": card.stability,
        "difficulty": card.difficulty,
        "due": card.due.isoformat(),
        "last_review": card.last_review.isoformat() if card.last_review else None,
    }


def estimate_fsrs_card(entry: dict) -> tuple[dict, str]:
    """SM-2 entry에서 FSRS Card 초기 상태를 추정."""
    from fsrs import Card, State as FsrsState
    from datetime import datetime, timezone

    sr_interval = entry.get("sr_interval", 1)
    mastery = entry.get("mastery", 0.0)
    sr_next_review = entry.get("sr_next_review")

    # stability ≈ interval (단, 최솟값 0.1)
    stability = max(float(sr_interval), 0.1)

    # difficulty: mastery 높을수록 낮은 difficulty (FSRS 범위 1–10)
    difficulty = max(1.0, min(10.0, 1.0 + (1.0 - mastery) * 9.0))

    # due date
    if sr_next_review:
        due = datetime.fromisoformat(sr_next_review).replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
        )
    else:
        due = datetime.now(timezone.utc)

    # last_review: due - interval days (근사)
    from datetime import timedelta
    last_review = due - timedelta(days=sr_interval)

    card = Card(
        state=FsrsState(2),         # Review 상태
        step=None,
        stability=stability,
        difficulty=difficulty,
        due=due,
        last_review=last_review,
    )

    fsrs_next_review = due.astimezone().strftime("%Y-%m-%d")
    return _card_to_dict(card), fsrs_next_review


def migrate(weak_data: dict, dry_run: bool = False) -> tuple[dict, int]:
    """모든 개념에 fsrs_card, fsrs_next_review 추가. 변환 건수 반환."""
    import copy
    migrated = copy.deepcopy(weak_data)
    count = 0

    for subject, concepts in migrated.items():
        for tag, entry in concepts.items():
            if entry.get("fsrs_card") is not None:
                continue  # 이미 마이그레이션 완료
            card_dict, fsrs_next_review = estimate_fsrs_card(entry)
            if not dry_run:
                entry["fsrs_card"] = card_dict
                entry["fsrs_next_review"] = fsrs_next_review
            count += 1
            if dry_run:
                print(
                    f"  [DRY] {subject}/{tag}: "
                    f"stability={card_dict['stability']:.2f}, "
                    f"difficulty={card_dict['difficulty']:.2f}, "
                    f"due={fsrs_next_review}"
                )

    return migrated, count


def enable_fsrs_in_config() -> None:
    """config.yaml의 scheduler 값을 fsrs로 설정."""
    import yaml

    with open(CONFIG_PATH, encoding="utf-8") as f:
        content = f.read()

    if "scheduler:" in content:
        import re
        content = re.sub(r"^scheduler:.*$", "scheduler: fsrs", content, flags=re.MULTILINE)
    else:
        content += "\nscheduler: fsrs\n"

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print("→ config.yaml scheduler: fsrs 설정 완료")


def main():
    parser = argparse.ArgumentParser(description="SM-2 → FSRS 마이그레이션")
    parser.add_argument("--dry-run", action="store_true", help="파일 수정 없이 미리보기")
    parser.add_argument("--enable", action="store_true", help="마이그레이션 후 config.yaml scheduler=fsrs 활성화")
    args = parser.parse_args()

    if not _FSRS_AVAILABLE:
        print("[ERROR] fsrs 패키지 미설치: pip install fsrs")
        sys.exit(1)

    config = load_config()
    pipeline_dir = get_study_paths(config).pipeline

    print(f"대상: {pipeline_dir / 'weak_concepts.json'}")
    weak_data = load_weak(pipeline_dir)

    total_concepts = sum(len(v) for v in weak_data.values())
    print(f"개념 수: {total_concepts}개 ({len(weak_data)}개 과목)")

    if args.dry_run:
        print("\n[DRY RUN] 실제 변경 없음\n")
        _, count = migrate(weak_data, dry_run=True)
        print(f"\n변환 예상: {count}개")
        return

    # 백업
    backup_path = backup_weak(pipeline_dir)
    print(f"백업 완료: {backup_path.name}")

    # 마이그레이션
    migrated_data, count = migrate(weak_data, dry_run=False)
    save_weak(pipeline_dir, migrated_data)
    print(f"마이그레이션 완료: {count}개 개념에 FSRS 카드 초기화")

    if args.enable:
        enable_fsrs_in_config()
        print(
            "\n주의: 1주일간 SM-2 결과와 FSRS 결과를 비교하여 검증 후 정식 전환을 권장합니다."
        )
    else:
        print(
            "\nFSRS 활성화하려면: python migrate_to_fsrs.py --enable"
            "\n또는 config.yaml에 'scheduler: fsrs' 추가"
        )


if __name__ == "__main__":
    main()
