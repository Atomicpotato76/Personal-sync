#!/usr/bin/env python3
"""approve_confusable.py -- 혼동 쌍(confusable_with) 등록/제거.

사용법:
  python approve_confusable.py add <subject> <tag_a> <tag_b>    - 양방향 혼동 쌍 등록
  python approve_confusable.py remove <subject> <tag_a> <tag_b> - 양방향 혼동 쌍 제거
  python approve_confusable.py list <subject>                    - 등록된 쌍 목록
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_weak(pipeline_dir: Path) -> dict:
    weak_path = pipeline_dir / "weak_concepts.json"
    if not weak_path.exists():
        return {}
    with open(weak_path, encoding="utf-8") as f:
        return json.load(f)


def save_weak(pipeline_dir: Path, data: dict) -> None:
    weak_path = pipeline_dir / "weak_concepts.json"
    with open(weak_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _ensure_fields(entry: dict) -> None:
    entry.setdefault("confusable_with", [])
    entry.setdefault("interleaving_eligible", False)


def cmd_add(config: dict, subject: str, tag_a: str, tag_b: str) -> None:
    pipeline_dir = Path(config.get("pipeline_dir", SCRIPT_DIR.parent))
    weak = load_weak(pipeline_dir)

    if subject not in weak:
        print(f"[ERROR] 과목 '{subject}'을 찾을 수 없습니다.")
        print(f"  가능한 과목: {', '.join(weak.keys())}")
        sys.exit(1)

    for tag in (tag_a, tag_b):
        if tag not in weak[subject]:
            print(f"[ERROR] 개념 '{tag}'을 '{subject}'에서 찾을 수 없습니다.")
            sys.exit(1)

    _ensure_fields(weak[subject][tag_a])
    _ensure_fields(weak[subject][tag_b])

    changed = False
    if tag_b not in weak[subject][tag_a]["confusable_with"]:
        weak[subject][tag_a]["confusable_with"].append(tag_b)
        changed = True
    if tag_a not in weak[subject][tag_b]["confusable_with"]:
        weak[subject][tag_b]["confusable_with"].append(tag_a)
        changed = True

    if changed:
        save_weak(pipeline_dir, weak)
        print(f"✓ 혼동 쌍 등록: {tag_a}  ↔  {tag_b}  (과목: {subject})")
    else:
        print(f"(이미 등록된 쌍: {tag_a} ↔ {tag_b})")


def cmd_remove(config: dict, subject: str, tag_a: str, tag_b: str) -> None:
    pipeline_dir = Path(config.get("pipeline_dir", SCRIPT_DIR.parent))
    weak = load_weak(pipeline_dir)

    if subject not in weak:
        print(f"[ERROR] 과목 '{subject}'을 찾을 수 없습니다.")
        sys.exit(1)

    changed = False
    for entry_tag, pair_tag in ((tag_a, tag_b), (tag_b, tag_a)):
        entry = weak[subject].get(entry_tag, {})
        pairs = entry.get("confusable_with", [])
        if pair_tag in pairs:
            pairs.remove(pair_tag)
            changed = True

    if changed:
        save_weak(pipeline_dir, weak)
        print(f"✓ 혼동 쌍 제거: {tag_a}  ↔  {tag_b}  (과목: {subject})")
    else:
        print(f"(등록되지 않은 쌍: {tag_a} ↔ {tag_b})")


def cmd_list(config: dict, subject: str) -> None:
    pipeline_dir = Path(config.get("pipeline_dir", SCRIPT_DIR.parent))
    weak = load_weak(pipeline_dir)
    concepts = weak.get(subject, {})
    if not concepts:
        print(f"과목 '{subject}'의 데이터가 없습니다.")
        return
    seen: set[frozenset] = set()
    print(f"\n[{subject}] 등록된 혼동 쌍:")
    found = False
    for tag, info in sorted(concepts.items()):
        for partner in info.get("confusable_with", []):
            key = frozenset([tag, partner])
            if key not in seen:
                seen.add(key)
                print(f"  {tag}  ↔  {partner}")
                found = True
    if not found:
        print("  (등록된 혼동 쌍 없음)")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    config = load_config()
    cmd = sys.argv[1]

    if cmd == "add":
        if len(sys.argv) < 5:
            print("사용법: python approve_confusable.py add <subject> <tag_a> <tag_b>")
            sys.exit(1)
        cmd_add(config, sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "remove":
        if len(sys.argv) < 5:
            print("사용법: python approve_confusable.py remove <subject> <tag_a> <tag_b>")
            sys.exit(1)
        cmd_remove(config, sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "list":
        if len(sys.argv) < 3:
            print("사용법: python approve_confusable.py list <subject>")
            sys.exit(1)
        cmd_list(config, sys.argv[2])
    else:
        print(f"[ERROR] 알 수 없는 명령: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
