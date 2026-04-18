#!/usr/bin/env python3
"""paper_review.py -- 캐시된 논문 관리 CLI.

사용법:
  python paper_review.py list [<과목>]       - 캐시된 논문 목록
  python paper_review.py read <doi_or_id>   - abstract + 요점 출력
  python paper_review.py link <doi_or_id> <concept_tag>
                                             - 논문을 개념 태그에 연결
"""

from __future__ import annotations

import json
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


def _papers_dir(config: dict) -> Path:
    papers_cfg = config.get("papers", {})
    cache_dir = papers_cfg.get("cache_dir", "")
    if cache_dir:
        p = Path(cache_dir)
    else:
        p = Path(config["pipeline_dir"]) / "cache" / "papers"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_all_papers(config: dict) -> list[dict]:
    """캐시 디렉토리의 모든 search_*.json에서 논문 목록 로드."""
    papers_dir = _papers_dir(config)
    all_papers: list[dict] = []
    seen_ids: set[str] = set()
    for cache_file in sorted(papers_dir.glob("search_*.json")):
        try:
            with open(cache_file, encoding="utf-8") as f:
                papers = json.load(f)
            for p in papers:
                pid = p.get("paper_id", "")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    all_papers.append(p)
        except (json.JSONDecodeError, OSError):
            continue
    return all_papers


def _find_paper(papers: list[dict], query_id: str) -> dict | None:
    """paper_id 또는 DOI(title 일부)로 논문 검색."""
    query_lower = query_id.lower()
    for p in papers:
        if p.get("paper_id", "").startswith(query_lower):
            return p
        if query_lower in p.get("title", "").lower():
            return p
    return None


def cmd_list(config: dict, subject_filter: str | None = None) -> None:
    """캐시된 논문 목록을 출력."""
    papers = _load_all_papers(config)
    if not papers:
        print("캐시된 논문이 없습니다.")
        print("synthesize.py를 실행하거나 paper_fetcher.py로 논문을 수집하세요.")
        return

    print(f"\n{'=' * 65}")
    print(f"  캐시된 논문 목록  ({len(papers)}편)")
    print(f"{'=' * 65}")
    print(f"  {'ID':<14} {'연도':>4} {'인용':>6}  {'제목'}")
    print(f"  {'-'*14} {'-'*4} {'-'*6}  {'-'*30}")

    for p in papers:
        year = p.get("year") or "    "
        cites = p.get("citation_count") or 0
        title = p.get("title", "")[:45]
        pid = p.get("paper_id", "")[:12]
        linked = "🔗" if p.get("_linked_concepts") else "  "
        has_ft = "📄" if p.get("full_text") else "  "
        print(f"  {pid:<14} {str(year):>4} {cites:>6}  {linked}{has_ft} {title}")

    print()


def cmd_read(config: dict, query_id: str) -> None:
    """논문 ID 또는 제목 일부로 abstract + 요점 출력."""
    papers = _load_all_papers(config)
    paper = _find_paper(papers, query_id)
    if paper is None:
        print(f"논문을 찾을 수 없습니다: {query_id}")
        print("python paper_review.py list  로 ID를 확인하세요.")
        return

    print(f"\n{'=' * 65}")
    print(f"  제목: {paper.get('title', '(없음)')}")
    print(f"  저자: {paper.get('authors', '(없음)')}")
    print(f"  연도: {paper.get('year', '?')}  |  인용: {paper.get('citation_count', 0)}회")
    print(f"  ID: {paper.get('paper_id', '?')}")
    cached_at = paper.get("cached_at", "")
    if cached_at:
        print(f"  캐시: {cached_at[:10]}")
    print(f"{'─' * 65}")

    abstract = paper.get("abstract", "")
    if abstract:
        print("\n  [Abstract]")
        for i in range(0, len(abstract), 80):
            print(f"  {abstract[i:i+80]}")
    else:
        print("\n  (Abstract 없음)")

    linked = paper.get("_linked_concepts", [])
    if linked:
        print(f"\n  연결된 개념: {', '.join(linked)}")

    full_text = paper.get("full_text", "")
    if full_text:
        print(f"\n  [본문 요점 — 처음 500자]")
        preview = full_text[:500].replace("\n", " ")
        print(f"  {preview}...")
    print()


def cmd_link(config: dict, query_id: str, concept_tag: str) -> None:
    """논문을 특정 concept_tag에 연결 (weak_concepts.json의 related_notes에 추가)."""
    papers = _load_all_papers(config)
    paper = _find_paper(papers, query_id)
    if paper is None:
        print(f"논문을 찾을 수 없습니다: {query_id}")
        return

    # concept_tag 존재 여부 확인 및 related_notes 업데이트
    from memory_manager import MemoryManager
    mem = MemoryManager(config)
    weak_data = mem._weak_data

    found_subject = None
    for subj, concepts in weak_data.items():
        if concept_tag in concepts:
            found_subject = subj
            break

    if found_subject is None:
        print(f"개념 태그를 찾을 수 없습니다: {concept_tag}")
        print("먼저 review를 통해 해당 개념을 등록하세요.")
        return

    paper_ref = f"paper:{paper.get('paper_id', query_id)}"
    entry = weak_data[found_subject][concept_tag]
    entry.setdefault("related_notes", [])
    if paper_ref not in entry["related_notes"]:
        entry["related_notes"].append(paper_ref)
        mem._save_json(mem.weak_path, weak_data)
        print(f"✓ 연결 완료: {paper.get('title', query_id)[:50]}")
        print(f"  → {found_subject}/{concept_tag}  (related_notes에 추가됨)")
    else:
        print(f"이미 연결되어 있습니다: {concept_tag} ↔ {paper.get('paper_id', query_id)}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    config = load_config()
    cmd = sys.argv[1]

    if cmd == "list":
        subject_filter = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_list(config, subject_filter)

    elif cmd == "read":
        if len(sys.argv) < 3:
            print("사용법: python paper_review.py read <paper_id 또는 제목 일부>")
            sys.exit(1)
        cmd_read(config, sys.argv[2])

    elif cmd == "link":
        if len(sys.argv) < 4:
            print("사용법: python paper_review.py link <paper_id> <concept_tag>")
            sys.exit(1)
        cmd_link(config, sys.argv[2], sys.argv[3])

    else:
        print(f"[ERROR] 알 수 없는 명령: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
