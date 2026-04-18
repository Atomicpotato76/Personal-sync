#!/usr/bin/env python3
"""competency_map.py -- 역량 지도 (Competency Map) 생성 CLI.

사용법:
  python competency_map.py map [<과목>]                  - ASCII 역량 지도 출력
  python competency_map.py export [--output <파일>]      - JSON 내보내기 (Obsidian Canvas 호환)
  python competency_map.py gap <과목>                    - 미추적 개념 후보 탐지
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"

sys.path.insert(0, str(SCRIPT_DIR))

_MASTERY_LEVELS = [
    ("mastered",   0.8,  "🟢", "mastered (≥80%)"),
    ("learning",   0.5,  "🟡", "learning  (50~80%)"),
    ("struggling", 0.0,  "🔴", "struggling (<50%)"),
]


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_weak_data(config: dict) -> dict:
    pipeline_dir = Path(config["pipeline_dir"])
    weak_path = pipeline_dir / "weak_concepts.json"
    if not weak_path.exists():
        return {}
    try:
        with open(weak_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _load_note_index(config: dict) -> dict:
    pipeline_dir = Path(config["pipeline_dir"])
    index_path = pipeline_dir / "cache" / "note_index.json"
    if not index_path.exists():
        return {}
    try:
        with open(index_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _classify(mastery: float) -> str:
    if mastery >= 0.8:
        return "mastered"
    if mastery >= 0.5:
        return "learning"
    return "struggling"


def cmd_map(config: dict, subject: str | None = None) -> None:
    """과목별 개념을 마스터리 수준으로 묶어 ASCII 트리 형태로 출력."""
    weak = _load_weak_data(config)
    if not weak:
        print("weak_concepts.json에 데이터가 없습니다.")
        return

    subjects = [subject] if subject else sorted(weak.keys())

    for subj in subjects:
        concepts = weak.get(subj, {})
        if not concepts:
            continue

        display_name = subj
        for folder, key in config.get("folder_mapping", {}).items():
            if key == subj:
                display_name = folder
                break

        buckets: dict[str, list[tuple[str, float]]] = {
            "mastered": [], "learning": [], "struggling": []
        }
        for tag, info in concepts.items():
            m = info.get("mastery", 0.0)
            buckets[_classify(m)].append((tag, m))
        for lst in buckets.values():
            lst.sort(key=lambda x: -x[1])

        total = len(concepts)
        avg = sum(info.get("mastery", 0.0) for info in concepts.values()) / max(total, 1)

        print(f"\n{'═' * 55}")
        print(f"  {display_name}  ({subj})   총 {total}개  평균: {avg:.0%}")
        print(f"{'═' * 55}")

        for level_key, _, icon, label in _MASTERY_LEVELS:
            bucket = buckets[level_key]
            print(f"\n  {icon} {label}  ({len(bucket)}개)")
            for tag, mastery in bucket:
                info = concepts[tag]
                priority = info.get("priority", "?")
                encounter = info.get("encounter_count", 0)
                confusable = info.get("confusable_with", [])
                bar = "█" * int(mastery * 10) + "░" * (10 - int(mastery * 10))
                line = f"    ├── {tag:<28} [{bar}] {mastery:.0%}"
                extras = []
                if priority == "high":
                    extras.append("⚠ high")
                if confusable:
                    extras.append(f"↔ {', '.join(confusable[:2])}")
                if encounter > 0:
                    extras.append(f"n={encounter}")
                if extras:
                    line += "  " + "  |  ".join(extras)
                print(line)

    print()


def cmd_export(config: dict, output_path: str = "competency.json") -> None:
    """역량 지도를 Obsidian Canvas / 외부 시각화 도구용 JSON으로 내보내기."""
    weak = _load_weak_data(config)
    if not weak:
        print("weak_concepts.json에 데이터가 없습니다.")
        return

    nodes: list[dict] = []
    edges: list[dict] = []
    seen_edges: set[tuple[str, str, str]] = set()

    for subj, concepts in weak.items():
        for tag, info in concepts.items():
            node_id = f"{subj}/{tag}"
            nodes.append({
                "id": node_id,
                "label": tag,
                "subject": subj,
                "mastery": info.get("mastery", 0.0),
                "priority": info.get("priority", "medium"),
                "level": _classify(info.get("mastery", 0.0)),
                "encounter_count": info.get("encounter_count", 0),
            })

            # confusable_with 엣지
            for target_tag in info.get("confusable_with", []):
                target_id = f"{subj}/{target_tag}"
                key = tuple(sorted([node_id, target_id]) + ["confusable"])
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append({
                        "source": node_id,
                        "target": target_id,
                        "type": "confusable",
                    })

            # cross_linked_concepts 엣지
            for link in info.get("cross_linked_concepts", []):
                t_subj = link.get("subject", "")
                t_tag = link.get("concept", "")
                if not t_subj or not t_tag:
                    continue
                target_id = f"{t_subj}/{t_tag}"
                key = tuple(sorted([node_id, target_id]) + ["cross_subject"])
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append({
                        "source": node_id,
                        "target": target_id,
                        "type": "cross_subject",
                        "strength": link.get("strength", "moderate"),
                    })

    out = Path(output_path)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"nodes": nodes, "edges": edges}, f, ensure_ascii=False, indent=2)

    print(f"역량 지도 내보내기 완료: {out}  ({len(nodes)}개 노드, {len(edges)}개 엣지)")


def cmd_gap(config: dict, subject: str) -> None:
    """note_index에서 자주 등장하는 단어 중 미추적 개념 후보를 탐지."""
    weak = _load_weak_data(config)
    note_index = _load_note_index(config)

    registered = set(weak.get(subject, {}).keys())

    # 해당 과목 노트의 TF 벡터에서 단어 빈도 합산
    word_freq: Counter = Counter()
    note_count = 0
    for path, info in note_index.get("notes", {}).items():
        if info.get("subject") != subject:
            continue
        note_count += 1
        for word, tf in info.get("tf", {}).items():
            word_freq[word] += tf

    if not word_freq:
        print(f"[{subject}] note_index에 해당 과목 노트가 없습니다.")
        print("먼저 synthesize.py 또는 memory_manager.embed_note()를 실행해 노트를 인덱싱하세요.")
        return

    # 단어 필터: 길이 ≥ 3, 숫자 제외, 등록된 개념 아님
    _STOPWORDS = {
        "the", "and", "with", "for", "that", "this", "from", "are", "can",
        "has", "not", "but", "have", "been", "also", "its", "more",
        "을", "를", "이", "가", "은", "는", "에", "도", "에서", "으로", "로",
        "의", "와", "과", "한", "것", "등", "수", "및", "내", "후", "전",
    }
    candidates = [
        (word, freq)
        for word, freq in word_freq.most_common(200)
        if word not in registered
        and word not in _STOPWORDS
        and len(word) >= 3
        and not re.fullmatch(r"[\d\s\-_.]+", word)
    ]

    print(f"\n[{subject}]  노트 {note_count}개 분석  |  등록된 개념: {len(registered)}개")
    print(f"{'─' * 55}")
    print("  미추적 개념 후보 (노트 내 빈도 합산 상위 순)\n")

    if not candidates:
        print("  추가 후보가 없습니다. 모든 주요 단어가 이미 추적되고 있습니다.")
        return

    print(f"  {'단어':<28} {'빈도합':>8}")
    print(f"  {'─'*28} {'─'*8}")
    for word, freq in candidates[:30]:
        print(f"  {word:<28} {freq:>8.4f}")
    print(f"\n  (등록하려면: memory_manager로 record_result() 호출 또는 weak_concepts.json 직접 추가)")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    config = load_config()
    cmd = sys.argv[1]

    if cmd == "map":
        subject = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_map(config, subject)

    elif cmd == "export":
        output = "competency.json"
        if "--output" in sys.argv:
            idx = sys.argv.index("--output")
            if idx + 1 < len(sys.argv):
                output = sys.argv[idx + 1]
        cmd_export(config, output)

    elif cmd == "gap":
        if len(sys.argv) < 3:
            print("사용법: python competency_map.py gap <과목>")
            sys.exit(1)
        cmd_gap(config, sys.argv[2])

    else:
        print(f"[ERROR] 알 수 없는 명령: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
