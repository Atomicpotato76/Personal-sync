"""explain.py -- 취약도 기반 개념 설명 MCP 도구."""
from __future__ import annotations

import json
from pathlib import Path

from path_utils import get_study_paths


def _get_mastery_for_concept(concept: str, subject: str, config: dict) -> tuple[float, str, dict]:
    """개념의 mastery 값 + 관련 정보 조회.

    반환: (mastery, subject_key, info_dict)
    """
    paths = get_study_paths(config)
    wc_path = paths.pipeline / "weak_concepts.json"
    if not wc_path.exists():
        return 0.5, subject, {}

    with open(wc_path, encoding="utf-8") as f:
        weak = json.load(f)

    concept_lower = concept.lower().replace(" ", "_")

    # 특정 과목 지정
    if subject:
        concepts = weak.get(subject, {})
        for tag, info in concepts.items():
            if concept_lower in tag.lower() or tag.lower() in concept_lower:
                return info.get("mastery", 0.5), subject, info
        return 0.5, subject, {}

    # 전체 과목 검색
    for subj_key, concepts in weak.items():
        for tag, info in concepts.items():
            if concept_lower in tag.lower() or tag.lower() in concept_lower:
                return info.get("mastery", 0.5), subj_key, info

    return 0.5, subject or "", {}


def _determine_depth(mastery: float) -> tuple[str, str]:
    """mastery 값에 따라 설명 깊이와 스타일 결정.

    반환: (depth_label, instruction)
    """
    if mastery < 0.3:
        return "기초", (
            "이 학생은 해당 개념을 거의 모르는 상태입니다.\n"
            "가장 기본적인 정의부터 시작하세요.\n"
            "일상적인 비유를 사용하고, 단계별로 천천히 설명하세요.\n"
            "전제 지식을 가정하지 마세요."
        )
    elif mastery < 0.5:
        return "초급", (
            "이 학생은 기본 개념은 들어봤지만 이해가 불안정합니다.\n"
            "핵심 정의를 명확히 짚고, 예시를 통해 이해를 다져주세요.\n"
            "흔히 혼동하는 포인트를 짚어주면 좋습니다."
        )
    elif mastery < 0.7:
        return "중급", (
            "이 학생은 기본은 알지만 응용이 약합니다.\n"
            "핵심 포인트를 빠르게 정리하고, 적용 예시 중심으로 설명하세요.\n"
            "시험에 나올 수 있는 변형 문제 패턴도 언급하세요."
        )
    elif mastery < 0.9:
        return "상급", (
            "이 학생은 꽤 잘 알고 있습니다.\n"
            "심화 내용이나 예외 케이스 중심으로 설명하세요.\n"
            "다른 개념과의 연결, 시험 출제 포인트를 강조하세요."
        )
    else:
        return "숙달", (
            "이 학생은 이 개념을 잘 이해하고 있습니다.\n"
            "최신 연구 동향이나 응용 사례 위주로 간결하게 설명하세요.\n"
            "관련 심화 주제를 추천해주세요."
        )


def explain_concept(concept: str, subject: str, config: dict) -> str:
    """취약도 기반 개념 설명 생성.

    LLM 라우터를 사용하여 설명을 생성하되,
    학생의 mastery에 따라 프롬프트 깊이를 조절합니다.
    """
    mastery, subj_key, concept_info = _get_mastery_for_concept(concept, subject, config)
    depth_label, depth_instruction = _determine_depth(mastery)

    folder_map = config.get("folder_mapping", {})
    reverse = {v: k for k, v in folder_map.items()}
    subj_display = reverse.get(subj_key, subj_key) if subj_key else "(미지정)"

    # 오답 이력 참조
    mistake_context = ""
    mistakes = concept_info.get("recent_mistakes", [])
    if mistakes:
        recent = mistakes[-3:]  # 최근 3개
        mistake_lines = [f"  - {m.get('date', '?')[:10]}: {m.get('memo', '(메모 없음)')}" for m in recent]
        mistake_context = "\n최근 오답 이력:\n" + "\n".join(mistake_lines)

    # 노트 검색으로 컨텍스트 보강
    note_context = ""
    try:
        from mcp_tools.notes import search_notes
        note_results = search_notes(concept, subj_key, config)
        if "검색 결과가 없습니다" not in note_results:
            # 첫 300자만 컨텍스트로 사용
            note_context = f"\n\n학생의 기존 노트 참고:\n{note_results[:500]}"
    except Exception:
        pass

    # LLM으로 설명 생성
    from llm_router import LLMRouter
    router = LLMRouter(config)

    prompt = f"""다음 개념에 대해 설명해주세요.

개념: {concept}
과목: {subj_display}
학생 수준: {depth_label} (mastery: {mastery:.0%})
{mistake_context}
{note_context}

{depth_instruction}

규칙:
- 한국어로 설명, 학술 용어는 영문 유지
- Markdown 형식
- 핵심 포인트를 명확히 구분
- 구체적인 예시 포함
"""

    result = router.generate(prompt, task_type="user_response")

    if not result:
        return (
            f"## {concept}\n\n"
            f"LLM 설명 생성에 실패했습니다.\n\n"
            f"**현재 상태:** mastery {mastery:.0%} ({depth_label})\n"
            f"**과목:** {subj_display}\n\n"
            f"교재에서 직접 찾아보시겠어요? "
            f"study_get_textbook을 호출하면 관련 페이지를 볼 수 있습니다."
        )

    # 메타 정보 헤더 추가
    header = (
        f"> **{concept}** | {subj_display} | "
        f"mastery: {mastery:.0%} ({depth_label})\n\n"
    )

    return header + result
