"""papers.py -- 캐싱된 논문 검색 MCP 도구."""
from __future__ import annotations

import json
import re
from pathlib import Path

from path_utils import get_study_paths


def get_related_papers(topic: str, max_results: int, config: dict) -> str:
    """캐싱된 논문에서 관련 내용 검색."""
    paths = get_study_paths(config)
    papers_cache = paths.cache / "papers"
    pubmed_cache = paths.cache / "pubmed"

    results: list[dict] = []
    topic_lower = topic.lower()
    topic_terms = topic_lower.split()

    # 1. Semantic Scholar 캐시 검색
    if papers_cache.exists():
        for meta_file in papers_cache.glob("*.json"):
            if meta_file.name == "marker_cache":
                continue
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                continue

            # 메타데이터 또는 리스트
            papers = data if isinstance(data, list) else [data]
            for paper in papers:
                title = paper.get("title", "")
                abstract = paper.get("abstract", "")
                searchable = (title + " " + abstract).lower()

                if any(term in searchable for term in topic_terms):
                    results.append({
                        "title": title,
                        "year": paper.get("year", "?"),
                        "citations": paper.get("citationCount", 0),
                        "abstract": (abstract[:300] + "...") if len(abstract) > 300 else abstract,
                        "source": "Semantic Scholar",
                    })

    # 2. PubMed 캐시 검색
    if pubmed_cache.exists():
        for cache_file in pubmed_cache.glob("*.json"):
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                continue

            articles = data if isinstance(data, list) else data.get("articles", [data])
            for article in articles:
                title = article.get("title", "")
                abstract = article.get("abstract", "")
                searchable = (title + " " + abstract).lower()

                if any(term in searchable for term in topic_terms):
                    results.append({
                        "title": title,
                        "year": article.get("year", "?"),
                        "citations": 0,
                        "abstract": (abstract[:300] + "...") if len(abstract) > 300 else abstract,
                        "source": "PubMed",
                    })

    # 3. marker-pdf 추출 텍스트 캐시 검색
    marker_cache = papers_cache / "marker_cache"
    if marker_cache.exists():
        for txt_file in marker_cache.glob("*.txt"):
            try:
                text = txt_file.read_text(encoding="utf-8")
            except Exception:
                continue
            text_lower = text.lower()
            if any(term in text_lower for term in topic_terms):
                # 매칭 문단 추출
                paragraphs = text.split("\n\n")
                matched = []
                for para in paragraphs:
                    if any(term in para.lower() for term in topic_terms):
                        matched.append(para.strip()[:200])
                if matched:
                    results.append({
                        "title": txt_file.stem.replace("_", " "),
                        "year": "",
                        "citations": 0,
                        "abstract": " | ".join(matched[:3]),
                        "source": "Full-text cache",
                    })

    if not results:
        return f"'{topic}'에 대한 캐싱된 논문을 찾을 수 없습니다."

    # 중복 제거 + 인용수 순 정렬
    seen_titles = set()
    unique = []
    for r in results:
        t = r["title"].lower()[:50]
        if t not in seen_titles:
            seen_titles.add(t)
            unique.append(r)
    unique.sort(key=lambda x: x["citations"], reverse=True)
    unique = unique[:max_results]

    lines = [f"## 관련 논문: '{topic}'", f"총 {len(unique)}개\n"]
    for i, r in enumerate(unique, 1):
        lines.append(f"### {i}. {r['title']}")
        meta = []
        if r["year"]:
            meta.append(str(r["year"]))
        if r["citations"]:
            meta.append(f"citations: {r['citations']}")
        meta.append(f"source: {r['source']}")
        lines.append(f"_{' | '.join(meta)}_\n")
        if r["abstract"]:
            lines.append(f"> {r['abstract']}\n")

    return "\n".join(lines)
