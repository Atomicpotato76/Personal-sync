#!/usr/bin/env python3
"""textbook_quiz.py -- 교재 챕터 연습문제 추출 + 유형 분류 + 학습계획 생성.

v3.1: queue/ 호환 퀴즈 JSON 생성 + 교재/첨부자료 이미지 크롭 지원.
"""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from path_utils import get_study_paths

logger = logging.getLogger("pipeline")

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ══════════════════════════════════════════════════════════════
# 교재 연습문제 추출
# ══════════════════════════════════════════════════════════════

def extract_textbook_problems(subject: str, chapter: str, config: dict) -> Optional[str]:
    """교재 PDF에서 챕터 끝 연습문제 페이지를 추출.

    교재 끝부분(마지막 10-15% 페이지)에 Problems/Exercises 섹션이 있는 경우가 많음.
    """
    from source_extractor import extract_pdf_text

    subject_cfg = config["subjects"].get(subject)
    if not subject_cfg or not subject_cfg.get("textbook"):
        return None

    notes_base = get_study_paths(config).notes_base
    tb_path = notes_base / subject_cfg["folder"] / subject_cfg["textbook"]
    if not tb_path.exists():
        logger.warning(f"교재 없음: {tb_path}")
        return None

    chapter_pages = subject_cfg.get("textbook_chapter_pages", {})
    if chapter not in chapter_pages:
        logger.warning(f"챕터 페이지 매핑 없음: {chapter}")
        return None

    start, end = chapter_pages[chapter]
    # 연습문제는 보통 챕터 후반부 (마지막 20% 페이지)
    problem_start = end - max(int((end - start) * 0.3), 5)
    text = extract_pdf_text(tb_path, pages=(problem_start, end))

    if not text or len(text.strip()) < 50:
        return None

    return text


# ══════════════════════════════════════════════════════════════
# LLM으로 퀴즈 유형 분류 + 문제 정리
# ══════════════════════════════════════════════════════════════

def classify_and_format_problems(
    raw_problems: str,
    subject: str,
    chapter: str,
    config: dict,
) -> Optional[dict]:
    """교재 연습문제를 LLM으로 분류·정리하여 구조화된 퀴즈 데이터 생성."""
    from llm_router import LLMRouter
    router = LLMRouter(config)

    prompt = f"""다음은 대학교 교재의 챕터 끝 연습문제 텍스트입니다.
이 문제들을 분석하여 JSON으로 정리해주세요.

규칙:
- 각 문제를 유형별로 분류해주세요
- 유형: "conceptual" (개념 이해), "mechanism" (메커니즘 작성), "prediction" (생성물 예측), "comparison" (비교 설명), "calculation" (계산), "naming" (명명법)
- 난이도: "easy", "medium", "hard"
- 한 문제당 핵심 키워드(concept_tags) 추출
- 교재 연습문제 번호가 있으면 보존
- Output ONLY valid JSON. No markdown fences.

출력 형식:
{{
  "chapter": "{chapter}",
  "total_problems": 숫자,
  "problems": [
    {{
      "number": "문제 번호 (예: 4.1, 4.2a)",
      "type": "conceptual|mechanism|prediction|comparison|calculation|naming",
      "question": "문제 텍스트 (한국어 번역 또는 원문)",
      "difficulty": "easy|medium|hard",
      "concept_tags": ["tag1", "tag2"],
      "hint": "풀이 힌트 (1문장)"
    }}
  ]
}}

--- 교재 연습문제 텍스트 ---
{raw_problems[:8000]}
"""

    data = router.generate_json(prompt, task_type="quiz_generate")
    return data


# ══════════════════════════════════════════════════════════════
# 학습 계획 생성
# ══════════════════════════════════════════════════════════════

def generate_study_plan(
    quiz_results: dict,
    weak_concepts: dict,
    subject: str,
    config: dict,
) -> str:
    """퀴즈 결과 + weak_concepts 기반으로 학습 계획 MD 생성."""
    from llm_router import LLMRouter
    router = LLMRouter(config)

    # 문제 유형별 정답률 계산
    type_stats = {}
    for p in quiz_results.get("problems", []):
        ptype = p.get("type", "unknown")
        result = p.get("review", {}).get("result")
        if ptype not in type_stats:
            type_stats[ptype] = {"total": 0, "correct": 0, "wrong": 0, "partial": 0}
        type_stats[ptype]["total"] += 1
        if result == "correct":
            type_stats[ptype]["correct"] += 1
        elif result == "wrong":
            type_stats[ptype]["wrong"] += 1
        elif result == "partial":
            type_stats[ptype]["partial"] += 1

    # weak_concepts에서 이 과목의 취약 개념
    subject_weak = weak_concepts.get(subject, {})
    high_priority = [
        tag for tag, info in subject_weak.items()
        if info.get("priority") == "high"
    ]

    stats_text = json.dumps(type_stats, ensure_ascii=False, indent=2)
    weak_text = ", ".join(high_priority[:10]) if high_priority else "(없음)"

    prompt = f"""다음은 학생의 교재 연습문제 풀이 결과와 취약 개념 목록입니다.
이를 바탕으로 맞춤 학습 계획을 작성해주세요.

규칙:
- 한국어로 작성, 영문 용어 유지
- Markdown 형식
- "## 학습 계획" 헤딩으로 시작
- 문제 유형별 정답률 분석 → 취약 유형 식별
- 취약 개념과 취약 유형을 교차 분석
- 구체적인 복습 전략 제시 (어떤 교재 페이지, 어떤 유형 문제를 더 풀어야 하는지)
- 우선순위: 🔴 긴급 / 🟡 주의 / 🟢 양호

--- 유형별 결과 ---
{stats_text}

--- 취약 개념 (high priority) ---
{weak_text}

--- 과목 ---
{subject}
"""

    plan = router.generate(prompt, task_type="synthesis_deep")
    return plan or ""


# ══════════════════════════════════════════════════════════════
# 교재 퀴즈를 synthesize.py에서 호출하는 인터페이스
# ══════════════════════════════════════════════════════════════

def add_textbook_quiz_section(
    synthesis_md: str,
    subject: str,
    note_text: str,
    config: dict,
) -> str:
    """정리노트 끝에 교재 연습문제 섹션 추가."""
    # 노트에서 챕터 추출
    chapter = _detect_chapter(note_text, config, subject)
    if not chapter:
        print("    교재 챕터 감지 실패, 퀴즈 섹션 건너뜀")
        return synthesis_md

    print(f"    교재 퀴즈 추출 중 ({chapter})...")
    raw = extract_textbook_problems(subject, chapter, config)
    if not raw:
        print("    교재 연습문제 텍스트 추출 실패")
        return synthesis_md

    print("    퀴즈 유형 분류 중...")
    quiz_data = classify_and_format_problems(raw, subject, chapter, config)
    if not quiz_data or not quiz_data.get("problems"):
        print("    퀴즈 분류 실패")
        return synthesis_md

    # MD 섹션 생성
    problems = quiz_data["problems"]
    lines = [
        "\n\n---\n",
        f"## 교재 연습문제 ({chapter.upper()})\n",
        f"총 {len(problems)}문제 | 유형별 분류 완료\n",
    ]

    type_counts = {}
    for p in problems:
        t = p.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    type_labels = {
        "conceptual": "개념 이해",
        "mechanism": "메커니즘",
        "prediction": "생성물 예측",
        "comparison": "비교 설명",
        "calculation": "계산",
        "naming": "명명법",
    }
    lines.append("\n| 유형 | 문제 수 |")
    lines.append("|------|---------|")
    for t, c in sorted(type_counts.items()):
        label = type_labels.get(t, t)
        lines.append(f"| {label} | {c} |")
    lines.append("")

    for p in problems[:10]:  # 최대 10문제 표시
        diff_mark = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(p.get("difficulty"), "⚪")
        ptype = type_labels.get(p.get("type"), p.get("type", ""))
        lines.append(f"### {p.get('number', '?')}. [{diff_mark} {ptype}]")
        lines.append(f"\n{p.get('question', '')}\n")
        if p.get("hint"):
            lines.append(f"> 💡 힌트: {p['hint']}\n")
        lines.append("**My Answer:**\n\n")
        lines.append("- [ ] correct  - [ ] wrong  - [ ] partial\n")
        lines.append("---\n")

    synthesis_md += "\n".join(lines)
    print(f"    교재 퀴즈 {len(problems)}문제 추가 완료")

    # 퀴즈 데이터 JSON 저장 (학습계획용)
    quiz_cache = get_study_paths(config).cache / "textbook_quiz"
    quiz_cache.mkdir(parents=True, exist_ok=True)
    cache_path = quiz_cache / f"{subject}_{chapter}.json"
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, ensure_ascii=False, indent=2)

    return synthesis_md


def _detect_chapter(note_text: str, config: dict, subject: str) -> Optional[str]:
    """노트 텍스트에서 챕터 키 감지."""
    chapter_pages = config["subjects"].get(subject, {}).get("textbook_chapter_pages", {})
    if not chapter_pages:
        return None

    patterns = [
        r"[Cc]h(?:apter)?\s*(\d+)",
        r"(\d+)\s*장",
        r"Chapter\s+(\d+)",
        r"챕터\s*(\d+)",
        r"[Cc]p\s*(\d+)",              # "Cp 5 까지" 패턴
        r"(\d+)p\b",                    # 페이지 참조에서 챕터 추론은 안 함
    ]
    found_chapters = set()
    for pat in patterns[:5]:  # 마지막 패턴(페이지) 제외
        for m in re.finditer(pat, note_text):
            ch_key = f"ch{m.group(1)}"
            if ch_key in chapter_pages:
                found_chapters.add(ch_key)

    if found_chapters:
        # 여러 챕터 발견 시 가장 많이 언급된 것 우선
        return sorted(found_chapters)[-1]  # 마지막 챕터 (보통 더 최신)

    # 페이지 번호에서 역매핑
    page_refs = re.findall(r"(\d+)p\b", note_text)
    for p_str in page_refs:
        p = int(p_str)
        for ch_key, (start, end) in chapter_pages.items():
            if start <= p <= end:
                return ch_key

    return None


# ══════════════════════════════════════════════════════════════
# v3.1: 교재 이미지 크롭 + queue 호환 퀴즈 JSON 생성
# ══════════════════════════════════════════════════════════════

def crop_problem_images(
    subject: str,
    chapter: str,
    config: dict,
) -> list[dict]:
    """교재/첨부자료 PDF에서 연습문제 관련 이미지를 추출·크롭.

    반환: [{path, page, description, problem_ref}]
    """
    from source_extractor import extract_pdf_images

    subject_cfg = config["subjects"].get(subject, {})
    paths = get_study_paths(config)
    cache_dir = paths.cache / "textbook_quiz" / "images" / f"{subject}_{chapter}"
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_images: list[dict] = []

    # 1순위: 교재 PDF 이미지 (챕터 페이지 범위 내)
    chapter_pages = subject_cfg.get("textbook_chapter_pages", {})
    if chapter in chapter_pages and subject_cfg.get("textbook"):
        notes_base = paths.notes_base
        tb_path = notes_base / subject_cfg["folder"] / subject_cfg["textbook"]
        if tb_path.exists():
            start, end = chapter_pages[chapter]
            # 연습문제는 챕터 후반부
            problem_start = end - max(int((end - start) * 0.3), 5)
            tb_images = extract_pdf_images(
                tb_path,
                cache_dir / "textbook",
                pages=(problem_start, end),
                min_size=3000,
            )
            for img in tb_images:
                img["source"] = "textbook"
                img["chapter"] = chapter
                all_images.append(img)

    # 2순위: 강의자료/첨부자료 이미지
    slides_dir_name = subject_cfg.get("slides_dir", "PDF/")
    subject_dir = paths.notes_base / subject_cfg.get("folder", "")
    slides_dir = subject_dir / slides_dir_name
    if slides_dir.exists():
        slide_pattern = subject_cfg.get("slide_pattern", "*.pdf")
        # 챕터 번호로 슬라이드 파일 매칭
        ch_num = re.search(r"\d+", chapter)
        if ch_num:
            for slide_file in slides_dir.glob(slide_pattern):
                if ch_num.group() in slide_file.stem:
                    slide_images = extract_pdf_images(
                        slide_file,
                        cache_dir / "slides",
                        min_size=3000,
                    )
                    for img in slide_images:
                        img["source"] = "slides"
                        img["slide_file"] = slide_file.name
                        all_images.append(img)
                    break  # 첫 매칭 슬라이드만

    logger.info(f"교재 퀴즈 이미지 추출: {len(all_images)}개 ({subject}/{chapter})")
    return all_images


def generate_textbook_quiz_to_queue(
    subject: str,
    chapter: str,
    config: dict,
) -> Optional[Path]:
    """교재 연습문제를 queue/ 호환 JSON으로 생성하여 저장.

    Quiz Review에서 바로 사용 가능한 형식으로 출력.
    반환: 생성된 JSON 파일 경로 (queue/)
    """
    # 교재 연습문제 텍스트 추출
    raw = extract_textbook_problems(subject, chapter, config)
    if not raw:
        logger.warning(f"교재 연습문제 텍스트 없음: {subject}/{chapter}")
        return None

    # LLM으로 분류·정리
    quiz_data = classify_and_format_problems(raw, subject, chapter, config)
    if not quiz_data or not quiz_data.get("problems"):
        logger.warning(f"교재 퀴즈 분류 실패: {subject}/{chapter}")
        return None

    # 이미지 크롭
    images = crop_problem_images(subject, chapter, config)
    image_map: dict[int, list[dict]] = {}
    for img in images:
        page = img.get("page", -1)
        image_map.setdefault(page, []).append(img)

    # queue/ 호환 JSON 생성
    now = datetime.now()
    quiz_id = f"textbook_{subject}_{chapter}_{now.strftime('%m%d%H%M%S')}"

    items = []
    for i, p in enumerate(quiz_data.get("problems", [])):
        item: dict = {
            "type": p.get("type", "conceptual"),
            "question": p.get("question", ""),
            "expected_answer_keys": [p.get("hint", "")] if p.get("hint") else [],
            "difficulty": p.get("difficulty", "medium"),
            "concept_tags": p.get("concept_tags", []),
            "problem_number": p.get("number", str(i + 1)),
            "source": "textbook",
            "review": {"result": None, "memo": None, "reviewed_at": None},
        }

        # 해당 문제에 관련 이미지 첨부
        # 간단한 휴리스틱: 이미지를 순서대로 문제에 매핑
        if images and i < len(images):
            item["image_path"] = images[i].get("path", "")
            item["image_source"] = images[i].get("source", "")

        items.append(item)

    queue_data = {
        "id": quiz_id,
        "subject": subject,
        "source_note": f"textbook_{chapter}",
        "source_type": "textbook",
        "chapter": chapter,
        "generated_at": now.isoformat(timespec="seconds"),
        "status": "queue",
        "items": items,
        "total_problems": len(items),
        "image_count": len(images),
    }

    # queue/에 저장
    paths = get_study_paths(config)
    paths.queue.mkdir(parents=True, exist_ok=True)
    queue_path = paths.queue / f"{quiz_id}.json"
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump(queue_data, f, ensure_ascii=False, indent=2)

    # 캐시에도 저장
    cache_dir = paths.cache / "textbook_quiz"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{subject}_{chapter}.json"
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, ensure_ascii=False, indent=2)

    logger.info(f"교재 퀴즈 queue 저장: {quiz_path} ({len(items)} items, {len(images)} images)")
    return queue_path


def generate_all_chapters_quiz(subject: str, config: dict) -> list[Path]:
    """과목의 모든 챕터 연습문제를 queue에 일괄 생성."""
    subject_cfg = config["subjects"].get(subject, {})
    chapter_pages = subject_cfg.get("textbook_chapter_pages", {})

    results = []
    for chapter in sorted(chapter_pages.keys()):
        path = generate_textbook_quiz_to_queue(subject, chapter, config)
        if path:
            results.append(path)
    return results
