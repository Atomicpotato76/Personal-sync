#!/usr/bin/env python3
"""retire_low_quality.py -- 품질 낮은 퀴즈 문항 은퇴 처리.

사용법:
  python retire_low_quality.py list [--threshold 2]      - 낮은 품질 문항 목록
  python retire_low_quality.py run  [--threshold 2]      - 일괄 은퇴 처리
  python retire_low_quality.py stats                     - 품질 분포 통계
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from path_utils import get_study_paths, apply_env_path_overrides

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"

sys.path.insert(0, str(SCRIPT_DIR))


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return apply_env_path_overrides(yaml.safe_load(f) or {})


def _get_item_quality(item: dict) -> int | None:
    """item_quality 필드를 item 루트 또는 review 서브딕트에서 찾는다."""
    q = item.get("item_quality")
    if q is None:
        q = item.get("review", {}).get("item_quality")
    return q


def _iter_all_quizzes(config: dict):
    """(jf, data, item_idx, item) 을 yield."""
    paths = get_study_paths(config)
    for search_dir in (paths.queue, paths.approved):
        if not search_dir.exists():
            continue
        for jf in sorted(search_dir.glob("*.json")):
            try:
                with open(jf, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            for idx, item in enumerate(data.get("items", [])):
                yield jf, data, idx, item


def cmd_list(config: dict, threshold: int = 2) -> None:
    found = False
    for jf, data, idx, item in _iter_all_quizzes(config):
        q = _get_item_quality(item)
        if q is None or q > threshold or item.get("retired"):
            continue
        found = True
        status = "[이미 은퇴]" if item.get("retired") else f"[품질 {q}]"
        q_preview = item.get("question", "")[:80]
        tags = ", ".join(item.get("concept_tags", []))
        print(f"  {status} {data['id']} / Q{idx + 1}")
        print(f"    {q_preview}")
        print(f"    tags: {tags}")
        print()
    if not found:
        print(f"품질 ≤ {threshold}인 미은퇴 문항이 없습니다.")


def cmd_run(config: dict, threshold: int = 2, dry_run: bool = False) -> None:
    retired_count = 0
    files_modified: dict = {}

    for jf, data, idx, item in _iter_all_quizzes(config):
        q = _get_item_quality(item)
        if q is None or q > threshold or item.get("retired"):
            continue
        if dry_run:
            print(f"  [DRY-RUN] 은퇴 대상: {data['id']} Q{idx + 1} (품질 {q})")
        else:
            item["retired"] = True
        retired_count += 1
        files_modified[str(jf)] = (jf, data)

    if not dry_run:
        for jf_path, data in files_modified.values():
            with open(jf_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    if dry_run:
        print(f"\n[DRY-RUN] 은퇴 예정: {retired_count}개 문항 (파일 변경 없음)")
    else:
        print(f"✓ 은퇴 처리 완료: {retired_count}개 문항, {len(files_modified)}개 파일 수정됨")


def cmd_stats(config: dict) -> None:
    from collections import Counter
    quality_dist: Counter = Counter()
    retired_count = 0
    unrated_count = 0
    total = 0

    for _, data, _, item in _iter_all_quizzes(config):
        total += 1
        if item.get("retired"):
            retired_count += 1
            continue
        q = _get_item_quality(item)
        if q is None:
            unrated_count += 1
        else:
            quality_dist[q] += 1

    print(f"\n품질 통계 (전체 {total}개 문항)\n")
    print(f"  은퇴됨: {retired_count}개")
    print(f"  미평가: {unrated_count}개")
    print()

    if quality_dist:
        bar_len = 20
        max_count = max(quality_dist.values())
        for level in range(1, 6):
            count = quality_dist.get(level, 0)
            filled = int(count / max(max_count, 1) * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)
            label = ["매우나쁨", "나쁨   ", "보통   ", "좋음   ", "완벽   "][level - 1]
            print(f"  {level}점 {label}: [{bar}] {count}개")
    else:
        print("  (품질 평가 데이터 없음)")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    config = load_config()
    cmd = sys.argv[1]

    threshold = 2
    if "--threshold" in sys.argv:
        idx = sys.argv.index("--threshold")
        if idx + 1 < len(sys.argv):
            threshold = int(sys.argv[idx + 1])

    if cmd == "list":
        cmd_list(config, threshold)
    elif cmd == "run":
        dry = "--dry-run" in sys.argv
        cmd_run(config, threshold, dry_run=dry)
    elif cmd == "stats":
        cmd_stats(config)
    else:
        print(f"[ERROR] 알 수 없는 명령: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
