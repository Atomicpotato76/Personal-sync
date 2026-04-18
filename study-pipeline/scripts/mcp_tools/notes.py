"""notes.py -- 학습 노트 검색 MCP 도구."""
from __future__ import annotations

import re
from pathlib import Path

from path_utils import get_study_paths


def search_notes(query: str, subject: str, config: dict) -> str:
    """노트 파일에서 키워드를 검색하여 관련 문단 반환."""
    paths = get_study_paths(config)
    folder_mapping = config.get("folder_mapping", {})
    reverse_map = {v: k for k, v in folder_mapping.items()}
    excluded = {"퀴즈", "정리"}

    # 대상 과목 결정
    if subject:
        subjects = {subject: config["subjects"].get(subject, {})}
    else:
        subjects = config.get("subjects", {})

    results: list[dict] = []
    query_lower = query.lower()
    query_terms = query_lower.split()

    for subj_key, subj_cfg in subjects.items():
        folder = subj_cfg.get("folder", "")
        subj_dir = paths.notes_base / folder
        if not subj_dir.exists():
            continue

        for md_file in subj_dir.rglob("*.md"):
            # 출력 폴더 제외
            try:
                rel = md_file.relative_to(subj_dir)
            except ValueError:
                continue
            if any(p in excluded for p in rel.parts):
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            text_lower = text.lower()
            if not any(term in text_lower for term in query_terms):
                continue

            # 매칭 문단 추출
            paragraphs = text.split("\n\n")
            matched = []
            for para in paragraphs:
                if any(term in para.lower() for term in query_terms):
                    # 문단 앞뒤 잘라서 최대 300자
                    trimmed = para.strip()[:300]
                    if trimmed:
                        matched.append(trimmed)

            if matched:
                display_name = reverse_map.get(subj_key, subj_key)
                results.append({
                    "file": md_file.name,
                    "subject": display_name,
                    "subject_key": subj_key,
                    "matches": matched[:5],  # 최대 5개 문단
                    "total_matches": len(matched),
                })

    if not results:
        return f"'{query}'에 대한 검색 결과가 없습니다."

    # 포맷팅
    lines = [f"## 검색 결과: '{query}'", f"총 {len(results)}개 파일에서 발견\n"]
    for r in results[:10]:
        lines.append(f"### {r['file']} ({r['subject']})")
        for m in r["matches"]:
            # 검색어 하이라이트
            highlighted = m
            for term in query_terms:
                highlighted = re.sub(
                    re.escape(term),
                    f"**{term}**",
                    highlighted,
                    flags=re.IGNORECASE,
                )
            lines.append(f"> {highlighted}")
            lines.append("")
        if r["total_matches"] > 5:
            lines.append(f"_(+{r['total_matches'] - 5}개 더)_\n")

    return "\n".join(lines)
