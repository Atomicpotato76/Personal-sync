#!/usr/bin/env python3
"""mcp_server.py -- Study Pipeline MCP Server for Claude Desktop.

Claude Desktop 앱에서 학습 데이터에 직접 접근하여:
  - 노트 검색, 교재 조회, 취약 개념 확인
  - 맥락 기반 개념 설명 요청
  - 즉석 퀴즈 생성 + 결과 기록

실행:
  python mcp_server.py              # stdio transport (Claude Desktop용)
  python mcp_server.py --test       # 자체 테스트

Claude Desktop 설정:
  %APPDATA%/Claude/claude_desktop_config.json 에 등록
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from path_utils import apply_env_path_overrides

# ── 경로 설정 ──
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# 로깅 (stderr로 → Claude Desktop이 stdout은 MCP 프로토콜로 사용)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp_server")

# ── Config 로드 ──
CONFIG_PATH = Path(
    os.environ.get("STUDY_PIPELINE_CONFIG", str(SCRIPT_DIR / "config.yaml"))
)

def _load_config() -> dict:
    import yaml

    with open(CONFIG_PATH, encoding="utf-8") as f:
        return apply_env_path_overrides(yaml.safe_load(f) or {})

# ══════════════════════════════════════════════════════════════
# MCP Server
# ══════════════════════════════════════════════════════════════

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "study-pipeline",
    instructions=(
        "Study Pipeline MCP 서버입니다. "
        "학생의 학습 노트, 교재, 취약 개념, 퀴즈 이력에 접근하여 "
        "맥락 기반의 개인화된 학습 지원을 제공합니다. "
        "또한 Hermes 일정 관리 계층을 통해 오늘/이번 주 학습 일정을 조정할 수 있습니다. "
        "한국어로 응답하되 학술 용어는 영문을 유지합니다."
    ),
)


# ──────────────────────────────────────────────────────────────
# Phase 1: 검색 + 조회
# ──────────────────────────────────────────────────────────────

@mcp.tool()
def study_search_notes(query: str, subject: str = "") -> str:
    """학습 노트에서 키워드를 검색합니다.

    Args:
        query: 검색할 키워드나 개념 (한국어/영어 모두 가능)
        subject: 과목 키 (organic_chem, genomics_ai, mycology). 비우면 전체 검색.

    Returns:
        매칭된 노트 내용 (파일명, 관련 문단)
    """
    config = _load_config()
    from mcp_tools.notes import search_notes
    return search_notes(query, subject, config)


@mcp.tool()
def study_get_weak_concepts(subject: str = "") -> str:
    """현재 취약한 개념 목록을 조회합니다. mastery, priority, 다음 복습일 포함.

    Args:
        subject: 과목 키. 비우면 전체 과목.

    Returns:
        취약 개념 목록 (mastery, priority, SR interval, next_review)
    """
    config = _load_config()
    from mcp_tools.concepts import get_weak_concepts
    return get_weak_concepts(subject, config)


@mcp.tool()
def study_get_textbook(subject: str, chapter: str = "", pages: str = "") -> str:
    """교재 PDF에서 특정 챕터/페이지의 텍스트를 추출합니다.

    Args:
        subject: 과목 키 (organic_chem 등)
        chapter: 챕터 키 (ch1, ch2, ...). 비우면 페이지로 조회.
        pages: 페이지 범위 "start-end" (예: "150-160"). chapter가 있으면 무시.

    Returns:
        교재 해당 부분의 텍스트
    """
    config = _load_config()
    from mcp_tools.textbook import get_textbook_content
    return get_textbook_content(subject, chapter, pages, config)


# ──────────────────────────────────────────────────────────────
# Phase 2: 심화 설명 + 이력
# ──────────────────────────────────────────────────────────────

@mcp.tool()
def study_explain_concept(concept: str, subject: str = "") -> str:
    """개념을 학생의 취약도에 맞춰 설명합니다.

    취약 개념(mastery < 0.5)이면 기초부터 상세히,
    보통(0.5~0.8)이면 핵심 포인트 중심으로,
    숙달(> 0.8)이면 심화·응용 관점으로 설명합니다.

    Args:
        concept: 설명할 개념 (영문 또는 한국어)
        subject: 과목 키. 비우면 자동 추정.

    Returns:
        개인화된 개념 설명 (취약도 기반 깊이 조절)
    """
    config = _load_config()
    from mcp_tools.explain import explain_concept
    return explain_concept(concept, subject, config)


@mcp.tool()
def study_get_quiz_history(subject: str = "", concept_tag: str = "") -> str:
    """퀴즈 풀이 이력을 조회합니다. 정답률, 오답 메모, 최근 시도 포함.

    Args:
        subject: 과목 키. 비우면 전체.
        concept_tag: 특정 개념 태그. 비우면 전체.

    Returns:
        퀴즈 이력 요약 (과목별 정답률, 오답 패턴)
    """
    config = _load_config()
    from mcp_tools.history import get_quiz_history
    return get_quiz_history(subject, concept_tag, config)


@mcp.tool()
def study_get_related_papers(topic: str, max_results: int = 3) -> str:
    """캐싱된 학술 논문에서 관련 내용을 검색합니다.

    Args:
        topic: 검색 주제 (영문 권장)
        max_results: 최대 결과 수 (기본 3)

    Returns:
        관련 논문 요약 (제목, 핵심 내용)
    """
    config = _load_config()
    from mcp_tools.papers import get_related_papers
    return get_related_papers(topic, max_results, config)


# ──────────────────────────────────────────────────────────────
# Phase 2.5: Hermes 일정 관리
# ──────────────────────────────────────────────────────────────

@mcp.tool()
def study_get_schedule(period: str = "day", anchor_date: str = "") -> str:
    """Hermes가 만든 일간/주간 학습 계획을 조회합니다.

    Args:
        period: "day" 또는 "week"
        anchor_date: 기준 날짜 YYYY-MM-DD. 비우면 오늘/이번 주.

    Returns:
        배치된 학습 블록, 미배치 후보, 다가오는 일정 요약
    """
    config = _load_config()
    from mcp_tools.schedule import get_schedule
    return get_schedule(period, anchor_date, config)


@mcp.tool()
def study_plan_week(anchor_date: str = "") -> str:
    """Hermes가 이번 주 학습 계획을 새로 생성합니다.

    Args:
        anchor_date: 주 시작 기준 날짜 YYYY-MM-DD. 비우면 이번 주.

    Returns:
        새로 생성된 주간 계획 요약
    """
    config = _load_config()
    from mcp_tools.schedule import plan_week
    return plan_week(anchor_date, config)


@mcp.tool()
def study_reschedule_task(period: str = "day", anchor_date: str = "") -> str:
    """학습 계획을 다시 계산합니다.

    Args:
        period: "day" 또는 "week"
        anchor_date: 기준 날짜 YYYY-MM-DD

    Returns:
        재계산된 Hermes 일정
    """
    config = _load_config()
    from mcp_tools.schedule import reschedule_schedule
    return reschedule_schedule(period, anchor_date, config)


@mcp.tool()
def study_add_exam_or_deadline(
    subject: str,
    when: str,
    title: str,
    details: str = "",
    kind: str = "exam",
) -> str:
    """시험/과제 일정을 추가하고 Hermes 주간 계획을 갱신합니다.

    Args:
        subject: 과목 키
        when: 날짜 YYYY-MM-DD
        title: 일정 제목
        details: 보충 설명
        kind: "exam" 또는 "deadline"

    Returns:
        추가 결과와 갱신된 주간 계획
    """
    config = _load_config()
    from mcp_tools.schedule import add_exam_or_deadline
    return add_exam_or_deadline(subject, when, title, details, kind, config)


# ──────────────────────────────────────────────────────────────
# Phase 3: 양방향 학습
# ──────────────────────────────────────────────────────────────

@mcp.tool()
def study_create_quiz(
    concept_tags: list[str],
    subject: str = "",
    difficulty: str = "medium",
    count: int = 3,
) -> str:
    """특정 개념에 대한 즉석 퀴즈를 생성하여 queue/에 저장합니다.

    Args:
        concept_tags: 퀴즈 대상 개념 태그 목록 (예: ["carbocation_stability", "sn2"])
        subject: 과목 키
        difficulty: 난이도 (easy, medium, hard)
        count: 문제 수 (기본 3)

    Returns:
        생성된 퀴즈 문제 목록 + quiz_id
    """
    config = _load_config()
    from mcp_tools.quiz import create_quiz
    return create_quiz(concept_tags, subject, difficulty, count, config)


@mcp.tool()
def study_record_result(
    concept_tag: str,
    result: str,
    subject: str = "",
    memo: str = "",
) -> str:
    """학습 결과를 기록합니다. weak_concepts + learning_history에 반영.

    대화 중 개념을 이해했거나 틀렸을 때 호출하여 spaced repetition에 반영합니다.

    Args:
        concept_tag: 개념 태그 (예: "carbocation_stability")
        result: 결과 ("correct", "wrong", "partial")
        subject: 과목 키
        memo: 오답 메모 (선택)

    Returns:
        업데이트된 mastery 정보
    """
    config = _load_config()
    from mcp_tools.quiz import record_result
    return record_result(concept_tag, result, subject, memo, config)


# ──────────────────────────────────────────────────────────────
# Resources (정적 컨텍스트)
# ──────────────────────────────────────────────────────────────

@mcp.resource("study://config")
def get_study_config() -> str:
    """현재 파이프라인 설정 요약 (과목 목록, LLM 설정 등)."""
    config = _load_config()
    subjects = config.get("subjects", {})
    folder_map = config.get("folder_mapping", {})
    reverse_map = {v: k for k, v in folder_map.items()}

    lines = ["# Study Pipeline 설정", ""]
    lines.append("## 과목")
    for key, cfg in subjects.items():
        display = reverse_map.get(key, key)
        tb = cfg.get("textbook", "(없음)")
        chapters = list(cfg.get("textbook_chapter_pages", {}).keys())
        lines.append(f"- **{display}** (`{key}`)")
        lines.append(f"  교재: {tb}")
        if chapters:
            lines.append(f"  챕터: {', '.join(chapters)}")

    llm = config.get("llm", {})
    lines.append("")
    lines.append("## LLM")
    lines.append(f"- LM Studio: {llm.get('lmstudio', {}).get('model', '(없음)')}")
    lines.append(f"- ChatGPT: {llm.get('chatgpt', {}).get('model', '(없음)')}")
    lines.append(f"- Claude: {llm.get('claude', {}).get('model', '(없음)')}")

    return "\n".join(lines)


@mcp.resource("study://due-reviews")
def get_due_reviews() -> str:
    """오늘 복습 예정인 개념 목록."""
    config = _load_config()
    from mcp_tools.concepts import get_due_reviews_today
    return get_due_reviews_today(config)


@mcp.resource("study://schedule-today")
def get_schedule_today() -> str:
    """Hermes 오늘 일정."""
    config = _load_config()
    from mcp_tools.schedule import get_schedule
    return get_schedule("day", "", config)


@mcp.resource("study://weekly-summary")
def get_weekly_summary() -> str:
    """이번 주 학습 통계 요약."""
    config = _load_config()
    from mcp_tools.history import get_weekly_summary
    return get_weekly_summary(config)


# ──────────────────────────────────────────────────────────────
# Prompts (대화 템플릿)
# ──────────────────────────────────────────────────────────────

@mcp.prompt()
def study_explain(concept: str, subject: str = "") -> str:
    """개념 설명 요청 프롬프트. 취약도 기반 깊이 자동 조절."""
    return (
        f"학생이 '{concept}' 개념에 대해 설명을 요청했습니다.\n\n"
        f"먼저 study_get_weak_concepts를 호출하여 이 학생의 해당 개념 mastery를 확인하세요.\n"
        f"그 다음 study_get_textbook으로 교재 관련 내용을 가져오세요.\n"
        f"study_search_notes로 학생의 기존 필기도 참고하세요.\n\n"
        f"mastery에 따라 설명 깊이를 조절하세요:\n"
        f"- < 0.5: 기초부터 차근차근, 비유와 예시 풍부하게\n"
        f"- 0.5~0.8: 핵심 포인트 중심, 노트에서 빠진 부분 보충\n"
        f"- > 0.8: 심화 응용, 시험 출제 포인트 강조\n\n"
        f"한국어로 설명하되 학술 용어는 영문 유지. "
        f"{'과목: ' + subject if subject else ''}"
    )


@mcp.prompt()
def study_quiz_me(topic: str, subject: str = "") -> str:
    """즉석 퀴즈 요청 프롬프트."""
    return (
        f"학생이 '{topic}'에 대한 퀴즈를 요청했습니다.\n\n"
        f"1. study_get_weak_concepts로 관련 취약 개념 확인\n"
        f"2. study_create_quiz로 적절한 난이도의 퀴즈 생성\n"
        f"3. 문제를 하나씩 출제하고, 학생 답변 후 채점\n"
        f"4. study_record_result로 결과 기록\n\n"
        f"격려하면서 진행하고, 틀린 문제는 왜 틀렸는지 설명해주세요. "
        f"{'과목: ' + subject if subject else ''}"
    )


@mcp.prompt()
def study_review() -> str:
    """오늘의 복습 세션 프롬프트."""
    return (
        "학생의 오늘 복습 세션을 시작합니다.\n\n"
        "1. study://due-reviews 리소스로 오늘 복습 예정 개념 확인\n"
        "2. 우선순위(priority: high → medium → low) 순서로 진행\n"
        "3. 각 개념에 대해:\n"
        "   a. 간단히 핵심 설명\n"
        "   b. 확인 질문 1개\n"
        "   c. 학생 답변 후 study_record_result로 기록\n"
        "4. 세션 끝에 study://weekly-summary로 전체 진도 보여주기\n\n"
        "격려하는 톤으로 진행하세요."
    )


@mcp.prompt()
def study_schedule_me(period: str = "day") -> str:
    """Hermes 일정 관리 프롬프트."""
    if period == "week":
        return (
            "학생의 이번 주 학습 일정을 정리합니다.\n\n"
            "1. study_get_schedule(period='week')로 현재 주간 계획을 확인\n"
            "2. 시험/과제 일정이 빠져 있으면 study_add_exam_or_deadline으로 먼저 추가\n"
            "3. 계획이 오래됐거나 오늘 상황이 바뀌었으면 study_reschedule_task(period='week')로 갱신\n"
            "4. 우선순위가 높은 복습 블록과 시험 대비 블록을 먼저 설명\n\n"
            "학생이 바로 실행할 수 있도록 오늘, 이번 주, 밀린 항목을 구분해 안내하세요."
        )
    return (
        "학생의 오늘 학습 흐름을 정리합니다.\n\n"
        "1. study://schedule-today 리소스로 오늘 배치된 블록 확인\n"
        "2. 일정이 비어 있거나 상황이 달라졌으면 study_reschedule_task(period='day') 호출\n"
        "3. 첫 블록부터 어떤 순서로 시작하면 좋은지 간단히 안내\n\n"
        "톤은 부담을 줄이고, 바로 시작할 수 있게 짧고 분명하게 설명하세요."
    )


# ══════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════

def main():
    if "--test" in sys.argv:
        _run_test()
    else:
        mcp.run(transport="stdio")


def _run_test():
    """자체 테스트 — MCP 없이 도구 직접 호출."""
    import io
    if sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("=== Study Pipeline MCP Server Test ===\n")

    tests = [
        ("[1] study_search_notes('alkyne')",      lambda: study_search_notes("alkyne", "organic_chem")),
        ("[2] study_get_weak_concepts('organic_chem')", lambda: study_get_weak_concepts("organic_chem")),
        ("[3] study://config resource",            get_study_config),
        ("[4] study://due-reviews resource",       get_due_reviews),
        ("[5] study_get_schedule('day')",          lambda: study_get_schedule("day", "")),
    ]

    for label, fn in tests:
        print(label)
        try:
            result = fn()
            print(result[:500] if result else "(no result)")
        except Exception as e:
            print(f"  ERROR: {e}")
        print()

    print("=== Test Complete ===")


if __name__ == "__main__":
    main()
