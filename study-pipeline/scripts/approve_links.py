#!/usr/bin/env python3
"""approve_links.py -- 교차과목 링크 검토 및 승인.

사용법:
  python approve_links.py list                              - 검토 대기 링크 목록
  python approve_links.py review                           - 대화형 승인/거절
  python approve_links.py add <src_subj> <src_tag> <tgt_subj> <tgt_tag> [strength]
                                                           - 직접 링크 등록
  python approve_links.py show <subject>                   - 과목의 교차 링크 보기
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from path_utils import apply_env_path_overrides

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return apply_env_path_overrides(yaml.safe_load(f) or {})


def cmd_list(config: dict) -> None:
    sys.path.insert(0, str(SCRIPT_DIR))
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    pending_data = mem._load_json(mem.pending_links_path)
    items = [p for p in pending_data.get("pending", []) if p.get("status") == "pending"]

    if not items:
        print("검토 대기 중인 교차 링크가 없습니다.")
        return

    print(f"\n검토 대기: {len(items)}개\n")
    for i, item in enumerate(items):
        print(
            f"  [{i+1}] {item['source_subject']} → {item['target_subject']}"
            f"\n      공통 개념: {item['shared_concept']}"
            f"\n      관계: {item['relationship'][:80]}"
            f"\n      강도: {item['strength']}  |  노트: {item['note_name']}"
            f"\n      감지: {item['detected_at'][:10]}"
        )
        print()


def cmd_review(config: dict) -> None:
    sys.path.insert(0, str(SCRIPT_DIR))
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    pending_data = mem._load_json(mem.pending_links_path)
    items = pending_data.get("pending", [])
    pending = [p for p in items if p.get("status") == "pending"]

    if not pending:
        print("검토 대기 중인 링크가 없습니다.")
        return

    approved = 0
    for item in pending:
        print(f"\n{'='*60}")
        print(f"  {item['source_subject']}  →  {item['target_subject']}")
        print(f"  공통 개념: {item['shared_concept']}")
        print(f"  관계: {item['relationship']}")
        print(f"  강도: {item['strength']}  |  노트: {item['note_name']}")
        print()

        # 이 링크에서 개념 수준 링크를 만들려면 source/target 개념 태그 필요
        weak = mem._weak_data
        src_subj = item["source_subject"]
        tgt_subj = item["target_subject"]
        src_concepts = list(weak.get(src_subj, {}).keys())
        tgt_concepts = list(weak.get(tgt_subj, {}).keys())

        action = input("a=승인(개념링크), s=건너뜀, r=거절, q=종료: ").strip().lower()

        if action == "q":
            break
        elif action == "r":
            item["status"] = "rejected"
            print("  → 거절됨")
        elif action == "a":
            if not src_concepts:
                print(f"  [WARN] '{src_subj}' 과목에 개념이 없습니다. 건너뜁니다.")
                item["status"] = "skipped"
                continue
            if not tgt_concepts:
                print(f"  [WARN] '{tgt_subj}' 과목에 개념이 없습니다. 건너뜁니다.")
                item["status"] = "skipped"
                continue

            print(f"\n  {src_subj} 개념 목록:")
            for i, c in enumerate(src_concepts[:20]):
                print(f"    {i+1}. {c}")
            src_raw = input("  소스 개념 번호 또는 이름 (Enter=건너뜀): ").strip()
            if not src_raw:
                item["status"] = "skipped"
                continue
            src_tag = src_concepts[int(src_raw) - 1] if src_raw.isdigit() else src_raw

            print(f"\n  {tgt_subj} 개념 목록:")
            for i, c in enumerate(tgt_concepts[:20]):
                print(f"    {i+1}. {c}")
            tgt_raw = input("  타겟 개념 번호 또는 이름 (Enter=건너뜀): ").strip()
            if not tgt_raw:
                item["status"] = "skipped"
                continue
            tgt_tag = tgt_concepts[int(tgt_raw) - 1] if tgt_raw.isdigit() else tgt_raw

            strength = item.get("strength", "moderate")
            ok = mem.approve_link(src_subj, src_tag, tgt_subj, tgt_tag, strength)
            if ok:
                item["status"] = "approved"
                print(f"  → 링크 등록: {src_tag} ({src_subj}) ↔ {tgt_tag} ({tgt_subj})")
                approved += 1
            else:
                print(f"  [ERROR] 링크 등록 실패 (개념 없음)")
                item["status"] = "skipped"
        else:
            item["status"] = "skipped"

    mem._save_json(mem.pending_links_path, pending_data)
    print(f"\n완료: {approved}개 링크 등록됨")


def cmd_add(config: dict, src_subj: str, src_tag: str, tgt_subj: str, tgt_tag: str, strength: str = "moderate") -> None:
    sys.path.insert(0, str(SCRIPT_DIR))
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    ok = mem.approve_link(src_subj, src_tag, tgt_subj, tgt_tag, strength)
    if ok:
        print(f"✓ 링크 등록: {src_tag} ({src_subj}) ↔ {tgt_tag} ({tgt_subj})  강도: {strength}")
    else:
        print(f"[ERROR] 개념을 찾을 수 없습니다: {src_subj}/{src_tag} 또는 {tgt_subj}/{tgt_tag}")
        sys.exit(1)


def cmd_show(config: dict, subject: str) -> None:
    sys.path.insert(0, str(SCRIPT_DIR))
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    concepts = mem._weak_data.get(subject, {})
    if not concepts:
        print(f"과목 '{subject}'의 데이터가 없습니다.")
        return

    print(f"\n[{subject}] 교차과목 링크:")
    found = False
    for tag, info in sorted(concepts.items()):
        links = info.get("cross_linked_concepts", [])
        if links:
            found = True
            for lk in links:
                print(f"  {tag}  ↔  {lk['concept']} ({lk['subject']})  강도: {lk['strength']}")
    if not found:
        print("  (등록된 교차 링크 없음)")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    config = load_config()
    cmd = sys.argv[1]

    if cmd == "list":
        cmd_list(config)
    elif cmd == "review":
        cmd_review(config)
    elif cmd == "add":
        if len(sys.argv) < 6:
            print("사용법: python approve_links.py add <src_subj> <src_tag> <tgt_subj> <tgt_tag> [strength]")
            sys.exit(1)
        strength = sys.argv[6] if len(sys.argv) > 6 else "moderate"
        cmd_add(config, sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], strength)
    elif cmd == "show":
        if len(sys.argv) < 3:
            print("사용법: python approve_links.py show <subject>")
            sys.exit(1)
        cmd_show(config, sys.argv[2])
    else:
        print(f"[ERROR] 알 수 없는 명령: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
