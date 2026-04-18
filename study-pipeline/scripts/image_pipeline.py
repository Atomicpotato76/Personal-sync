#!/usr/bin/env python3
"""image_pipeline.py -- 삽화 매칭: 교재→강의자료→자체생성 우선순위."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pipeline")


def match_images_for_section(
    section_text: str,
    textbook_images: list[dict],
    slides_images: list[dict],
    page_refs: dict,
) -> list[dict]:
    """섹션 텍스트에 적합한 이미지를 우선순위에 따라 매칭.

    반환: [{path, source, relevance_score}]
    """
    # 섹션에서 키워드 추출
    keywords = _extract_keywords(section_text)
    if not keywords:
        return []

    candidates = []

    # 1순위: 교재 이미지 (참조된 페이지 근처)
    ref_pages = set(page_refs.get("textbook_pages", []))
    for img in textbook_images:
        score = 0
        if img["page"] in ref_pages:
            score += 10
        # 페이지 근접성 (±3페이지 이내)
        for rp in ref_pages:
            if abs(img["page"] - rp) <= 3:
                score += 5
                break
        if score > 0:
            candidates.append({
                "path": img["path"],
                "source": "textbook",
                "page": img["page"],
                "score": score,
            })

    # 2순위: 강의자료 이미지
    ref_slides = set(page_refs.get("slide_pages", []))
    for img in slides_images:
        score = 0
        slide_num = img.get("slide", img.get("page", -1))
        if slide_num in ref_slides:
            score += 8
        if score > 0:
            candidates.append({
                "path": img["path"],
                "source": "slides",
                "slide": slide_num,
                "score": score,
            })

    # 점수순 정렬, 상위 3개
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:3]


def _extract_keywords(text: str) -> list[str]:
    """텍스트에서 영문 키워드 추출."""
    words = re.findall(r"[A-Za-z]{3,}", text)
    # 빈도 높은 것
    counts = {}
    for w in words:
        w_lower = w.lower()
        if w_lower not in {"the", "and", "for", "with", "that", "this", "from", "are", "was"}:
            counts[w_lower] = counts.get(w_lower, 0) + 1
    return sorted(counts, key=counts.get, reverse=True)[:5]


def generate_placeholder_image(
    section_title: str,
    output_path: Path,
    config: dict,
) -> Optional[str]:
    """matplotlib으로 간단한 플레이스홀더 이미지 생성."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(1, 1, figsize=(6, 2))
        ax.text(
            0.5, 0.5, section_title,
            ha="center", va="center",
            fontsize=14, style="italic",
            transform=ax.transAxes,
        )
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

        dpi = config.get("image_pipeline", {}).get("generate", {}).get("dpi", 150)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(output_path), dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        return str(output_path)
    except Exception as e:
        logger.warning(f"이미지 생성 실패: {e}")
        return None
