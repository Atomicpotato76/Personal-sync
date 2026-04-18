#!/usr/bin/env python3
"""marker_reader.py -- marker-pdf 기반 고급 PDF→Markdown 변환 (v3).

marker-pdf가 설치되어 있으면 사용하고, 없으면 pdfplumber/pymupdf fallback.
수식, 표, 이미지를 포함한 고품질 변환을 제공한다.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pipeline")

SCRIPT_DIR = Path(__file__).resolve().parent


def _cache_path(pdf_path: Path, cache_dir: Path, pages: Optional[tuple[int, int]] = None) -> Path:
    """PDF 파일의 캐시 경로를 생성."""
    name = pdf_path.stem
    h = hashlib.md5(str(pdf_path).encode()).hexdigest()[:8]
    suffix = f"_{pages[0]}_{pages[1]}" if pages else ""
    return cache_dir / f"{name}_{h}{suffix}.md"


def _is_marker_available() -> bool:
    """marker-pdf 설치 여부 확인."""
    try:
        from marker.converters.pdf import PdfConverter
        return True
    except ImportError:
        return False


def convert_with_marker(
    pdf_path: Path,
    cache_dir: Path,
    config: dict | None = None,
) -> Optional[str]:
    """marker-pdf로 PDF를 Markdown으로 변환.

    반환: Markdown 텍스트 (이미지 경로는 cache_dir 기준 상대경로)
    """
    cached = _cache_path(pdf_path, cache_dir)
    if cached.exists():
        logger.info(f"marker 캐시 사용: {cached.name}")
        return cached.read_text(encoding="utf-8")

    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
    except ImportError:
        logger.warning("marker-pdf 미설치: pip install marker-pdf")
        return None

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        img_dir = cache_dir / "images" / pdf_path.stem
        img_dir.mkdir(parents=True, exist_ok=True)

        models = create_model_dict()
        converter = PdfConverter(artifact_dict=models)
        rendered = converter(str(pdf_path))

        md_text = rendered.markdown
        # 이미지 저장
        for name, img in rendered.images.items():
            img_path = img_dir / name
            img.save(str(img_path))
            # Markdown 내 이미지 경로를 실제 경로로 치환
            md_text = md_text.replace(name, str(img_path))

        # 캐시에 저장
        cached.write_text(md_text, encoding="utf-8")
        logger.info(f"marker 변환 완료: {pdf_path.name} → {len(md_text)}자")
        return md_text

    except Exception as e:
        logger.error(f"marker 변환 실패 ({pdf_path.name}): {e}")
        return None


def convert_with_fallback(
    pdf_path: Path,
    cache_dir: Path,
    pages: Optional[tuple[int, int]] = None,
    config: dict | None = None,
) -> Optional[str]:
    """PDF→텍스트 변환: marker 우선, fallback으로 pdfplumber/pymupdf."""
    cached = _cache_path(pdf_path, cache_dir, pages)
    if cached.exists():
        return cached.read_text(encoding="utf-8")

    cache_dir.mkdir(parents=True, exist_ok=True)

    # marker가 설치되어 있고, 전체 페이지 변환인 경우
    marker_cfg = (config or {}).get("marker", {})
    if marker_cfg.get("enabled", True) and pages is None and _is_marker_available():
        result = convert_with_marker(pdf_path, cache_dir, config)
        if result and len(result.strip()) > 100:
            return result
        logger.info("marker 결과 부족, fallback 사용")

    # fallback: pdfplumber → pymupdf
    text = _extract_pdfplumber(pdf_path, pages)
    if not text or len(text.strip()) < 100:
        text = _extract_pymupdf(pdf_path, pages)

    if text and len(text.strip()) > 50:
        cached.write_text(text, encoding="utf-8")
        return text

    return None


def _extract_pdfplumber(pdf_path: Path, pages: Optional[tuple[int, int]] = None) -> Optional[str]:
    """pdfplumber로 텍스트 추출."""
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            start = pages[0] if pages else 0
            end = pages[1] if pages else len(pdf.pages)
            texts = []
            for i in range(start, min(end, len(pdf.pages))):
                text = pdf.pages[i].extract_text() or ""
                texts.append(text)
            result = "\n".join(texts)
            return result if result.strip() else None
    except Exception as e:
        logger.warning(f"pdfplumber 실패: {e}")
        return None


def _extract_pymupdf(pdf_path: Path, pages: Optional[tuple[int, int]] = None) -> Optional[str]:
    """pymupdf(fitz)로 텍스트 추출."""
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        start = pages[0] if pages else 0
        end = pages[1] if pages else len(doc)
        texts = []
        for i in range(start, min(end, len(doc))):
            texts.append(doc[i].get_text())
        doc.close()
        result = "\n".join(texts)
        return result if result.strip() else None
    except Exception as e:
        logger.error(f"pymupdf 실패: {e}")
        return None


def extract_paper_structured(
    pdf_path: Path,
    cache_dir: Path,
    config: dict | None = None,
) -> dict:
    """논문 PDF에서 구조화된 데이터 추출.

    반환: {
        "full_text": str,       # 전체 텍스트
        "abstract": str | None, # 초록
        "sections": list[dict], # [{"title": ..., "content": ...}]
        "references": list[str],# 참고문헌 리스트
        "figures": list[str],   # 이미지 경로
    }
    """
    md_text = convert_with_fallback(pdf_path, cache_dir, config=config)
    if not md_text:
        return {"full_text": "", "abstract": None, "sections": [], "references": [], "figures": []}

    import re

    # 섹션 파싱
    sections = []
    current_title = "Introduction"
    current_lines: list[str] = []

    for line in md_text.split("\n"):
        heading_match = re.match(r"^#{1,3}\s+(.+)", line)
        if heading_match:
            if current_lines:
                sections.append({"title": current_title, "content": "\n".join(current_lines).strip()})
            current_title = heading_match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections.append({"title": current_title, "content": "\n".join(current_lines).strip()})

    # Abstract 추출
    abstract = None
    for sec in sections:
        if "abstract" in sec["title"].lower():
            abstract = sec["content"]
            break

    # References 추출
    references = []
    for sec in sections:
        if "reference" in sec["title"].lower() or "bibliography" in sec["title"].lower():
            refs = re.findall(r"(?:^|\n)\s*\[?\d+\]?\s*(.+?)(?=\n\s*\[?\d+\]|\Z)", sec["content"], re.DOTALL)
            references = [r.strip() for r in refs if len(r.strip()) > 20]
            break

    # 이미지 경로 추출
    figures = re.findall(r"!\[.*?\]\((.+?)\)", md_text)

    return {
        "full_text": md_text,
        "abstract": abstract,
        "sections": sections,
        "references": references,
        "figures": figures,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("사용법: python marker_reader.py <PDF 경로>")
        sys.exit(1)

    pdf = Path(sys.argv[1])
    if not pdf.exists():
        print(f"파일 없음: {pdf}")
        sys.exit(1)

    cache = pdf.parent / ".marker_cache"
    print(f"marker 설치: {_is_marker_available()}")
    result = convert_with_fallback(pdf, cache)
    if result:
        print(f"\n변환 결과: {len(result)}자")
        print(result[:500])
    else:
        print("변환 실패")
