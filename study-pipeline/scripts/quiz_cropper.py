#!/usr/bin/env python3
"""quiz_cropper.py -- 교재 PDF의 연습문제 블록 크롭 유틸리티."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover - optional dependency
    fitz = None

from path_utils import get_study_paths

PROBLEM_PATTERNS: list[str] = [
    r"(?i)problem\s+\d+",
    r"(?i)exercise\s+\d+",
    r"(?i)practice\s+problem",
    r"(?i)end[- ]of[- ]chapter",
    r"(?i)worked\s+example",
    r"\d+\.\d+\s+(?=[A-Z])",
]


def _detect_chapter_num(chapter: str | None) -> int | None:
    if not chapter:
        return None
    match = re.search(r"(\d+)", chapter)
    if not match:
        return None
    return int(match.group(1))


def _resolve_textbook_path(subject_cfg: dict, subject_dir: Path) -> Path | None:
    textbook_raw = subject_cfg.get("textbook")
    if not textbook_raw:
        return None
    textbook_path = subject_dir / str(textbook_raw)
    if not textbook_path.exists():
        return None
    return textbook_path


def _iter_problem_blocks(page: Any, patterns: list[re.Pattern[str]]) -> list[tuple[Any, str]]:
    matches: list[tuple[Any, str]] = []
    for block in page.get_text("blocks"):
        if len(block) < 5:
            continue
        x0, y0, x1, y1, text = block[:5]
        text = str(text or "").strip()
        if not text:
            continue
        if any(pattern.search(text) for pattern in patterns):
            rect = fitz.Rect(float(x0), float(y0), float(x1), float(y1))
            matches.append((rect, text))
    return matches


def crop_textbook_problems(
    subject: str,
    chapter: str | None,
    config: dict,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """교재에서 문제 영역을 PNG로 크롭하고 index JSON을 생성한다.

    fallback 정책:
    - 교재 경로 없음 / 파일 없음: skipped
    - 패턴 매칭 0건: no_matches
    - 크롭 에러: error
    """
    log = logger or logging.getLogger("pipeline")
    subject_cfg = config.get("subjects", {}).get(subject, {})
    paths = get_study_paths(config)
    subject_dir = paths.notes_base / str(subject_cfg.get("folder", ""))
    textbook_path = _resolve_textbook_path(subject_cfg, subject_dir)

    if fitz is None:
        return {"status": "skipped", "reason": "pymupdf_unavailable", "count": 0}

    if textbook_path is None:
        return {"status": "skipped", "reason": "textbook_path_missing", "count": 0}

    chapter_num = _detect_chapter_num(chapter)
    chapter_key = f"ch{chapter_num}" if chapter_num else "unknown"
    output_dir = paths.pipeline / "output" / f"{subject}_{chapter_key}_quiz" / "textbook_problems"
    output_dir.mkdir(parents=True, exist_ok=True)

    chapter_pages = subject_cfg.get("textbook_chapter_pages", {})
    page_range = chapter_pages.get(chapter_key)
    start_idx = max(0, int(page_range[0]) - 1) if page_range else 0

    patterns = [re.compile(p) for p in PROBLEM_PATTERNS]
    problems: list[dict[str, Any]] = []

    try:
        doc = fitz.open(str(textbook_path))
    except Exception as exc:
        return {"status": "error", "reason": f"open_failed:{exc}", "count": 0}

    try:
        end_idx = min(len(doc), int(page_range[1])) if page_range else len(doc)
        for page_idx in range(start_idx, end_idx):
            page = doc[page_idx]
            blocks = _iter_problem_blocks(page, patterns)
            for rect, text in blocks:
                prob_no = len(problems) + 1
                item_id = (
                    f"ch{chapter_num}_problem_{prob_no:02d}" if chapter_num else f"problem_{prob_no:02d}"
                )
                img_path = output_dir / f"{item_id}.png"
                pix = page.get_pixmap(clip=rect, dpi=220)
                pix.save(str(img_path))
                problems.append(
                    {
                        "id": item_id,
                        "page": page_idx + 1,
                        "type": "in-chapter",
                        "topic_tags": [],
                        "has_answer": False,
                        "image": img_path.name,
                        "matched_text": text[:200],
                    }
                )
    except Exception as exc:
        log.warning("교재 문제 크롭 실패: %s", exc)
        return {"status": "error", "reason": f"crop_failed:{exc}", "count": 0}
    finally:
        doc.close()

    if not problems:
        return {"status": "no_matches", "reason": "pattern_match_0", "count": 0}

    index_path = output_dir / "problem_index.json"
    index_path.write_text(
        json.dumps({"problems": problems}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "status": "ok",
        "reason": "",
        "count": len(problems),
        "output_dir": str(output_dir),
        "index_path": str(index_path),
    }
