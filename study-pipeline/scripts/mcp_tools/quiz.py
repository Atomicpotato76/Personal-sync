"""quiz.py -- 즉석 퀴즈 생성 + 결과 기록 MCP 도구."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from path_utils import get_study_paths


def create_quiz(
    concept_tags: list[str],
    subject: str,
    difficulty: str,
    count: int,
    config: dict,
) -> str:
    """LLM으로 즉석 퀴즈를 생성하여 queue/에 저장."""
    from llm_router import LLMRouter
    router = LLMRouter(config)

    folder_map = config.get("folder_mapping", {})
    reverse = {v: k for k, v in folder_map.items()}
    subj_display = reverse.get(subject, subject) if subject else "(전체)"

    tags_str = ", ".join(concept_tags)
    prompt = f"""다음 개념에 대한 퀴즈를 {count}문제 생성해주세요.

개념: {tags_str}
과목: {subj_display}
난이도: {difficulty}

규칙:
- 각 문제는 서술형 또는 단답형
- 한국어로 출제, 학술 용어는 영문 유지
- Output ONLY valid JSON, no markdown fences
- 형식:
{{
  "problems": [
    {{
      "type": "conceptual|mechanism|prediction|comparison",
      "question": "문제 텍스트",
      "expected_answer_keys": ["핵심 키워드1", "핵심 키워드2"],
      "difficulty": "{difficulty}",
      "concept_tags": ["tag1", "tag2"],
      "hint": "풀이 힌트 (1문장)"
    }}
  ]
}}
"""

    quiz_data = router.generate_json(prompt, task_type="quiz_generate")

    if not quiz_data or not quiz_data.get("problems"):
        return "퀴즈 생성에 실패했습니다. LLM 연결을 확인해주세요."

    # queue/ 호환 JSON 생성
    now = datetime.now()
    quiz_id = f"instant_{subject or 'general'}_{now.strftime('%m%d%H%M%S')}"

    items = []
    for p in quiz_data["problems"]:
        items.append({
            "type": p.get("type", "conceptual"),
            "question": p.get("question", ""),
            "expected_answer_keys": p.get("expected_answer_keys", []),
            "difficulty": p.get("difficulty", difficulty),
            "concept_tags": p.get("concept_tags", concept_tags),
            "hint": p.get("hint", ""),
            "review": {"result": None, "memo": None, "reviewed_at": None},
        })

    queue_data = {
        "id": quiz_id,
        "subject": subject or "general",
        "source_note": "mcp_instant_quiz",
        "source_type": "instant",
        "generated_at": now.isoformat(timespec="seconds"),
        "status": "queue",
        "items": items,
    }

    # queue/에 저장
    paths = get_study_paths(config)
    paths.queue.mkdir(parents=True, exist_ok=True)
    queue_path = paths.queue / f"{quiz_id}.json"
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump(queue_data, f, ensure_ascii=False, indent=2)

    # 응답 포맷팅
    lines = [
        f"## 퀴즈 생성 완료",
        f"ID: `{quiz_id}` | {len(items)}문제 | {difficulty}\n",
    ]
    for i, item in enumerate(items, 1):
        lines.append(f"### Q{i}. [{item['type']}]")
        lines.append(item["question"])
        if item.get("hint"):
            lines.append(f"\n> Hint: {item['hint']}")
        lines.append("")

    lines.append(f"_quiz_id: {quiz_id} — 대시보드 Quiz Review에서도 확인 가능_")

    return "\n".join(lines)


def record_result(
    concept_tag: str,
    result: str,
    subject: str,
    memo: str,
    config: dict,
) -> str:
    """학습 결과를 기록. weak_concepts + learning_history 갱신."""
    if result not in ("correct", "wrong", "partial"):
        return f"result는 'correct', 'wrong', 'partial' 중 하나여야 합니다. (입력: {result})"

    from memory_manager import MemoryManager
    mm = MemoryManager(config)

    # 결과 기록
    mm.record_result(
        subject=subject or "general",
        concepts=[concept_tag],
        result=result,
        source_note="mcp_desktop",
        memo=memo,
    )

    # 업데이트된 정보 조회
    paths = get_study_paths(config)
    wc_path = paths.pipeline / "weak_concepts.json"
    updated_info = {}
    if wc_path.exists():
        with open(wc_path, encoding="utf-8") as f:
            weak = json.load(f)
        subj_data = weak.get(subject or "general", {})
        for tag, info in subj_data.items():
            if concept_tag.lower() in tag.lower():
                updated_info = info
                break

    mastery = updated_info.get("mastery", "?")
    priority = updated_info.get("priority", "?")
    next_review = updated_info.get("sr_next_review", "?")
    interval = updated_info.get("sr_interval", "?")

    icon = {"correct": "✅", "wrong": "❌", "partial": "🟡"}.get(result, "?")

    return (
        f"{icon} **{concept_tag}** — {result}\n\n"
        f"- Mastery: {mastery if isinstance(mastery, str) else f'{mastery:.0%}'}\n"
        f"- Priority: {priority}\n"
        f"- 다음 복습: {next_review} ({interval}일 후)\n"
        + (f"- 메모: {memo}\n" if memo else "")
    )
