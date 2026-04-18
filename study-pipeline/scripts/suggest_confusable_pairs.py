#!/usr/bin/env python3
"""suggest_confusable_pairs.py -- 혼동하기 쉬운 개념 쌍 제안 도우미.

사용법:
  python suggest_confusable_pairs.py list                   - 과목별 개념 목록 출력
  python suggest_confusable_pairs.py suggest                - 자동 제안 (이름 유사도 기반)
  python suggest_confusable_pairs.py show <subject>         - 특정 과목의 현재 쌍 보기
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


def load_weak(config: dict) -> dict:
    pipeline_dir = Path(config.get("pipeline_dir", SCRIPT_DIR.parent))
    weak_path = pipeline_dir / "weak_concepts.json"
    if not weak_path.exists():
        return {}
    with open(weak_path, encoding="utf-8") as f:
        return json.load(f)


def _jaccard(a: str, b: str) -> float:
    """단어 토큰 Jaccard 유사도 (간단한 자동 제안용)."""
    tokens_a = set(a.lower().replace("_", " ").split())
    tokens_b = set(b.lower().replace("_", " ").split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def cmd_list(config: dict) -> None:
    weak = load_weak(config)
    if not weak:
        print("weak_concepts.json이 없거나 비어 있습니다.")
        return
    for subject, concepts in sorted(weak.items()):
        display = config.get("folder_mapping", {})
        display_name = {v: k for k, v in display.items()}.get(subject, subject)
        print(f"\n[{display_name}]  (subject key: {subject})")
        for tag, info in sorted(concepts.items()):
            existing = info.get("confusable_with", [])
            eligible = info.get("interleaving_eligible", False)
            pair_text = f"  → 혼동 쌍: {', '.join(existing)}" if existing else ""
            elig_text = " [인터리빙 대상]" if eligible else " [초기노출]"
            print(f"  {tag}{elig_text}{pair_text}")


def cmd_suggest(config: dict, threshold: float = 0.3) -> None:
    weak = load_weak(config)
    if not weak:
        print("weak_concepts.json이 없거나 비어 있습니다.")
        return

    found_any = False
    for subject, concepts in sorted(weak.items()):
        tags = list(concepts.keys())
        suggestions: list[tuple[str, str, float]] = []
        for i, a in enumerate(tags):
            for b in tags[i + 1:]:
                score = _jaccard(a, b)
                if score >= threshold:
                    suggestions.append((a, b, score))
                # 이미 연결된 쌍도 표시
                if b in concepts[a].get("confusable_with", []) or a in concepts[b].get("confusable_with", []):
                    continue

        if not suggestions:
            continue

        found_any = True
        display = {v: k for k, v in config.get("folder_mapping", {}).items()}.get(subject, subject)
        print(f"\n[{display}] 자동 제안 (유사도 >= {threshold:.0%}):")
        for a, b, score in sorted(suggestions, key=lambda x: -x[2]):
            print(f"  {a}  ↔  {b}  (유사도 {score:.0%})")
        print(f"\n  → 쌍 추가: python approve_confusable.py add {subject} <tag_a> <tag_b>")

    if not found_any:
        print(f"유사도 {threshold:.0%} 이상인 제안 쌍이 없습니다.")


def cmd_show(config: dict, subject: str) -> None:
    weak = load_weak(config)
    concepts = weak.get(subject, {})
    if not concepts:
        print(f"과목 '{subject}'의 데이터가 없습니다.")
        return
    print(f"\n[{subject}] 현재 혼동 쌍:")
    has_pairs = False
    for tag, info in sorted(concepts.items()):
        pairs = info.get("confusable_with", [])
        if pairs:
            has_pairs = True
            print(f"  {tag}  ↔  {', '.join(pairs)}")
    if not has_pairs:
        print("  (등록된 혼동 쌍 없음)")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    config = load_config()
    cmd = sys.argv[1]

    if cmd == "list":
        cmd_list(config)
    elif cmd == "suggest":
        threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
        cmd_suggest(config, threshold)
    elif cmd == "show":
        if len(sys.argv) < 3:
            print("사용법: python suggest_confusable_pairs.py show <subject>")
            sys.exit(1)
        cmd_show(config, sys.argv[2])
    else:
        print(f"[ERROR] 알 수 없는 명령: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
