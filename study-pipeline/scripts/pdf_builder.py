#!/usr/bin/env python3
"""pdf_builder.py -- Markdown → PDF (reportlab Platypus, 한글 폰트 임베딩)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.fonts import addMapping
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    HRFlowable,
    Preformatted,
    Table,
    TableStyle,
    Image as RLImage,
    KeepTogether,
)

logger = logging.getLogger("pipeline")

SCRIPT_DIR = Path(__file__).resolve().parent

# ══════════════════════════════════════════════════════════════
# 폰트 등록
# ══════════════════════════════════════════════════════════════

_FONTS_REGISTERED = False
_FONT_NAMES: dict[str, str] = {
    "regular": "Helvetica",
    "bold": "Helvetica-Bold",
}


def _resolve_first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _register_fonts() -> None:
    global _FONTS_REGISTERED
    global _FONT_NAMES
    if _FONTS_REGISTERED:
        return

    font_dir = SCRIPT_DIR / "fonts"
    # 로컬 fonts/ 폴더 → OS 폰트 디렉토리 fallback
    win_fonts = Path("C:/Windows/Fonts")
    linux_fonts = Path("/usr/share/fonts")
    mac_fonts = Path("/Library/Fonts")
    font_candidates = {
        "regular": [
            font_dir / "NotoSansKR-Regular.ttf",
            win_fonts / "NotoSansKR-Regular.ttf",
            linux_fonts / "truetype/noto/NotoSansKR-Regular.ttf",
            linux_fonts / "opentype/noto/NotoSansCJK-Regular.ttc",
            mac_fonts / "NotoSansKR-Regular.ttf",
            mac_fonts / "AppleSDGothicNeo.ttc",
        ],
        "bold": [
            font_dir / "NotoSansKR-Bold.ttf",
            win_fonts / "NotoSansKR-Bold.ttf",
            linux_fonts / "truetype/noto/NotoSansKR-Bold.ttf",
            linux_fonts / "opentype/noto/NotoSansCJK-Bold.ttc",
            mac_fonts / "NotoSansKR-Bold.ttf",
            mac_fonts / "AppleSDGothicNeoB.ttc",
        ],
    }
    resolved = {key: _resolve_first_existing(paths) for key, paths in font_candidates.items()}
    can_use_noto_kr = resolved["regular"] is not None and resolved["bold"] is not None

    if can_use_noto_kr:
        try:
            pdfmetrics.registerFont(TTFont("NotoSansKR", str(resolved["regular"])))
            pdfmetrics.registerFont(TTFont("NotoSansKR-Bold", str(resolved["bold"])))
            pdfmetrics.registerFontFamily(
                "NotoSansKR",
                normal="NotoSansKR",
                bold="NotoSansKR-Bold",
                italic="NotoSansKR",
                boldItalic="NotoSansKR-Bold",
            )
            addMapping("NotoSansKR", 0, 0, "NotoSansKR")
            addMapping("NotoSansKR", 1, 0, "NotoSansKR-Bold")
            addMapping("NotoSansKR", 0, 1, "NotoSansKR")
            addMapping("NotoSansKR", 1, 1, "NotoSansKR-Bold")
            _FONT_NAMES = {"regular": "NotoSansKR", "bold": "NotoSansKR-Bold"}
        except Exception as e:
            logger.warning(f"NotoSansKR 폰트 등록 실패, 기본 폰트로 fallback 합니다: {e}")
    else:
        logger.warning(
            "NotoSansKR 폰트를 찾지 못해 기본 폰트(Helvetica)로 PDF를 생성합니다. "
            "한글이 깨질 수 있습니다."
        )

    _FONTS_REGISTERED = True


# ══════════════════════════════════════════════════════════════
# 스타일 정의
# ══════════════════════════════════════════════════════════════

def _build_styles() -> dict:
    """커스텀 Paragraph 스타일 딕셔너리."""
    _register_fonts()

    s = {}
    body_font = _FONT_NAMES["regular"]
    bold_font = _FONT_NAMES["bold"]

    s["body"] = ParagraphStyle(
        "KoBody", fontName=body_font, fontSize=11, leading=17,
        spaceBefore=2, spaceAfter=4,
    )
    s["h1"] = ParagraphStyle(
        "KoH1", fontName=bold_font, fontSize=20, leading=28,
        spaceBefore=0, spaceAfter=14,
        borderWidth=0, borderPadding=0,
    )
    s["h2"] = ParagraphStyle(
        "KoH2", fontName=bold_font, fontSize=15, leading=22,
        spaceBefore=16, spaceAfter=8,
        textColor=HexColor("#1a5276"),
    )
    s["h3"] = ParagraphStyle(
        "KoH3", fontName=bold_font, fontSize=13, leading=19,
        spaceBefore=12, spaceAfter=6,
        textColor=HexColor("#2c3e50"),
    )
    s["bullet"] = ParagraphStyle(
        "KoBullet", fontName=body_font, fontSize=11, leading=17,
        leftIndent=18, spaceBefore=1, spaceAfter=1,
        bulletIndent=6,
    )
    s["code"] = ParagraphStyle(
        "KoCode", fontName="Courier", fontSize=10, leading=14,
        leftIndent=12, spaceBefore=4, spaceAfter=4,
        backColor=HexColor("#f4f4f4"),
    )
    s["quote"] = ParagraphStyle(
        "KoQuote", fontName=body_font, fontSize=11, leading=17,
        leftIndent=18, spaceBefore=4, spaceAfter=4,
        textColor=HexColor("#2c3e50"),
        borderWidth=0,
    )
    s["exam"] = ParagraphStyle(
        "KoExam", fontName=bold_font, fontSize=11, leading=17,
        leftIndent=8, spaceBefore=4, spaceAfter=4,
        backColor=HexColor("#fef9e7"),
    )
    s["prof"] = ParagraphStyle(
        "KoProf", fontName=body_font, fontSize=11, leading=17,
        leftIndent=12, spaceBefore=4, spaceAfter=4,
        backColor=HexColor("#eafaf1"),
        textColor=HexColor("#1e8449"),
    )
    return s


# ══════════════════════════════════════════════════════════════
# Markdown → reportlab Story
# ══════════════════════════════════════════════════════════════

def _escape_xml(text: str) -> str:
    """reportlab Paragraph XML에서 안전하게 사용할 수 있도록 이스케이프."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def _chem_subscript(text: str) -> str:
    """화학식의 숫자 첨자를 reportlab <sub>/<sup> 태그로 변환.

    처리 패턴:
      H2SO4 → H<sub>2</sub>SO<sub>4</sub>
      CO2   → CO<sub>2</sub>
      CH3OH → CH<sub>3</sub>OH
      Na+   → Na<sup>+</sup>
      O2-   → O<sup>2-</sup>
      C6H5  → C<sub>6</sub>H<sub>5</sub>
      NaNH2 → NaNH<sub>2</sub>
      sp2   → sp<sup>2</sup>
      sp3   → sp<sup>3</sup>
    """
    # sp2, sp3 → sp² sp³ (상첨자)
    text = re.sub(r"\bsp(\d)\b", r"sp<super>\1</super>", text)

    # 화학식 내 원소 뒤 숫자 → 하첨자
    # 패턴: 대문자(+소문자?) 뒤에 숫자 (예: H2, SO4, CH3, C6)
    text = re.sub(
        r"([A-Z][a-z]?)(\d+)(?=[A-Z\s\)\]\-\+≡=,;:\.·\"\'\uac00-\ud7a3→←↔]|$)",
        r"\1<sub>\2</sub>",
        text,
    )

    # 이온 전하 → 상첨자: Na+, Cl-, O2-, Fe3+
    text = re.sub(r"([A-Z][a-z]?)(\d*)([\+\-])(?=[\s\)\],;:\.]|$)", r"\1<super>\2\3</super>", text)

    return text


def _inline_format(text: str) -> str:
    """인라인 마크다운 + 화학식 첨자를 reportlab XML 태그로 변환."""
    # 먼저 XML 이스케이프
    text = _escape_xml(text)
    # **bold**
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # *italic*
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    # `code` → monospace
    text = re.sub(r"`(.+?)`", r'<font face="Courier">\1</font>', text)
    # 화학식 첨자 변환
    text = _chem_subscript(text)
    return text


def _make_image_flowable(img_path: str, max_width: float = 14 * cm) -> list:
    """이미지 경로로부터 reportlab Image + 캡션 flowable 생성."""
    p = Path(img_path)
    if not p.exists():
        return []
    try:
        from PIL import Image as PILImage
        with PILImage.open(str(p)) as im:
            w, h = im.size
        # 최대 폭에 맞춰 비례 축소
        if w > 0:
            ratio = min(max_width / w, 1.0)
            display_w = w * ratio
            display_h = h * ratio
            # 너무 크면 추가 축소
            if display_h > 12 * cm:
                ratio2 = (12 * cm) / display_h
                display_w *= ratio2
                display_h *= ratio2
        else:
            display_w, display_h = max_width, 6 * cm

        img = RLImage(str(p), width=display_w, height=display_h)
        # 캡션 (파일명 기반)
        _register_fonts()
        caption_style = ParagraphStyle(
            "ImgCaption", fontName=_FONT_NAMES["regular"], fontSize=9, leading=12,
            textColor=HexColor("#888888"), alignment=1,  # center
        )
        src_label = "교재" if "textbook" in str(p) else "강의자료" if "slides" in str(p) else "이미지"
        caption = Paragraph(f"[{src_label}] {p.stem}", caption_style)
        return [Spacer(1, 6), img, caption, Spacer(1, 6)]
    except Exception as e:
        logger.warning(f"이미지 삽입 실패 ({p.name}): {e}")
        return []


def md_to_story(md_text: str, images: list[dict] | None = None) -> list:
    """Markdown 텍스트를 reportlab Flowable 리스트로 변환."""
    styles = _build_styles()
    story = []
    lines = md_text.split("\n")
    in_code = False
    code_lines = []
    in_frontmatter = False
    section_count = 0
    images = images or []
    # 이미지를 섹션마다 분배 (있는 만큼)
    images_per_section = 1

    for line in lines:
        stripped = line.strip()

        # frontmatter 스킵
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue

        # 코드 블록
        if stripped.startswith("```"):
            if in_code:
                code_text = "\n".join(code_lines)
                story.append(Preformatted(code_text, styles["code"]))
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue

        # 빈 줄
        if not stripped:
            story.append(Spacer(1, 4))
            continue

        # 헤딩
        if stripped.startswith("# "):
            story.append(Paragraph(_inline_format(stripped[2:]), styles["h1"]))
            story.append(HRFlowable(width="100%", thickness=2, color=HexColor("#333333")))
            continue
        if stripped.startswith("## "):
            story.append(Paragraph(_inline_format(stripped[3:]), styles["h2"]))
            # 섹션 뒤에 매칭된 이미지 삽입
            if images:
                img_idx = section_count * images_per_section
                for j in range(images_per_section):
                    if img_idx + j < len(images):
                        flowables = _make_image_flowable(images[img_idx + j].get("path", ""))
                        story.extend(flowables)
                section_count += 1
            continue
        if stripped.startswith("### ") or stripped.startswith("#### "):
            text = re.sub(r"^#{3,4}\s+", "", stripped)
            story.append(Paragraph(_inline_format(text), styles["h3"]))
            continue

        # 시험 포인트
        if "시험 포인트" in stripped:
            story.append(Paragraph(_inline_format(stripped), styles["exam"]))
            continue

        # 교수님 코멘트
        if "교수님:" in stripped or "교수님 :" in stripped:
            story.append(Paragraph(_inline_format(stripped), styles["prof"]))
            continue

        # blockquote
        if stripped.startswith("> "):
            story.append(Paragraph(_inline_format(stripped[2:]), styles["quote"]))
            continue

        # 리스트
        if stripped.startswith("- ") or stripped.startswith("* ") or stripped.startswith("• "):
            content = re.sub(r"^[-*•]\s+", "", stripped)
            text = "• " + _inline_format(content)
            story.append(Paragraph(text, styles["bullet"]))
            continue

        # 번호 리스트
        m = re.match(r"^(\d+)\.\s+(.+)", stripped)
        if m:
            text = f"{m.group(1)}. " + _inline_format(m.group(2))
            story.append(Paragraph(text, styles["bullet"]))
            continue

        # 구분선
        if re.match(r"^-{3,}$", stripped):
            story.append(HRFlowable(width="100%", thickness=1, color=HexColor("#cccccc")))
            continue

        # 일반 텍스트
        story.append(Paragraph(_inline_format(stripped), styles["body"]))

    return story


# ══════════════════════════════════════════════════════════════
# build_pdf
# ══════════════════════════════════════════════════════════════

def build_pdf(
    md_content: str,
    output_path: Path,
    config: dict,
    images: list[dict] | None = None,
) -> None:
    """Markdown → PDF 변환 (reportlab Platypus, NotoSansKR 임베딩, 이미지 임베딩)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Study Notes",
        author="Pipeline v2",
    )

    story = md_to_story(md_content, images=images)
    doc.build(story)
    logger.info(f"PDF 생성: {output_path}")
