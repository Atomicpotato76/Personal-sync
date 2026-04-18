"""textbook.py -- 교재 내용 조회 MCP 도구."""
from __future__ import annotations

from pathlib import Path

from path_utils import get_study_paths


def get_textbook_content(
    subject: str, chapter: str, pages: str, config: dict
) -> str:
    """교재 PDF에서 텍스트 추출."""
    from source_extractor import extract_pdf_text

    subject_cfg = config.get("subjects", {}).get(subject)
    if not subject_cfg:
        available = list(config.get("subjects", {}).keys())
        return f"과목 '{subject}'을 찾을 수 없습니다. 사용 가능: {', '.join(available)}"

    tb_rel = subject_cfg.get("textbook")
    if not tb_rel:
        return f"{subject} 과목에 교재 PDF가 설정되어 있지 않습니다."

    paths = get_study_paths(config)
    tb_path = paths.notes_base / subject_cfg["folder"] / tb_rel
    if not tb_path.exists():
        return f"교재 파일을 찾을 수 없습니다: {tb_path}"

    # 페이지 범위 결정
    page_range = None

    if chapter:
        chapter_pages = subject_cfg.get("textbook_chapter_pages", {})
        if chapter not in chapter_pages:
            available = list(chapter_pages.keys())
            return f"챕터 '{chapter}'를 찾을 수 없습니다. 사용 가능: {', '.join(available)}"
        start, end = chapter_pages[chapter]
        page_range = (start, end)
    elif pages:
        try:
            parts = pages.split("-")
            start = int(parts[0])
            end = int(parts[1]) if len(parts) > 1 else start + 1
            page_range = (start, end)
        except (ValueError, IndexError):
            return f"페이지 형식 오류: '{pages}'. 예시: '150-160'"

    if page_range is None:
        return "chapter 또는 pages 파라미터를 지정해주세요."

    # 추출 범위 제한 (한 번에 최대 20페이지)
    start, end = page_range
    if end - start > 20:
        end = start + 20

    text = extract_pdf_text(tb_path, pages=(start, end))

    if not text or not text.strip():
        return f"페이지 {start}~{end}에서 텍스트를 추출하지 못했습니다."

    # 결과 포맷팅
    folder_map = config.get("folder_mapping", {})
    reverse = {v: k for k, v in folder_map.items()}
    subj_display = reverse.get(subject, subject)

    header = f"## 교재: {subj_display}"
    if chapter:
        header += f" — {chapter.upper()}"
    header += f" (p.{start}~{end})"

    # 텍스트가 너무 길면 잘라서 반환
    max_chars = 8000
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n... (이하 생략, 총 {len(text)}자)"

    return f"{header}\n\n{text}"
