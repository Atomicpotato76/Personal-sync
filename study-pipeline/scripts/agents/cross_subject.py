#!/usr/bin/env python3
"""cross_subject.py -- 교차과목 연결 탐색 에이전트 (Ollama)."""

from __future__ import annotations

from typing import Optional

from agents.base_agent import BaseAgent


class CrossSubjectAgent(BaseAgent):
    """여러 과목 간의 공통 개념을 탐색하고 연결."""

    agent_name = "cross_subject"
    task_type = "classify"  # Ollama로 실행
    system_prompt = (
        "You are an interdisciplinary learning connector. "
        "Find conceptual links between different university subjects. "
        "For example, organic chemistry reactions might connect to biochemistry in genomics. "
        "Always output valid JSON only."
    )

    def build_prompt(self, input_data: dict) -> Optional[str]:
        current_text = input_data.get("current_text", "")
        current_subject = input_data.get("current_subject", "")
        other_subjects = input_data.get("other_subjects", {})
        if not current_text:
            return None

        other_info = ""
        for subj_name, subj_keywords in other_subjects.items():
            keywords_str = ", ".join(subj_keywords[:10])
            other_info += f"\n- {subj_name}: {keywords_str}"

        return f"""현재 학습 중인 과목의 내용과 다른 과목들 사이의 연결 관계를 찾아주세요.

규칙:
- 공통 개념이나 원리를 식별
- 한 과목의 이해가 다른 과목에 어떻게 도움이 되는지 설명
- 교차 학습 시너지를 제안
- Output ONLY valid JSON.

출력 형식:
{{
  "current_subject": "{current_subject}",
  "connections": [
    {{
      "other_subject": "연결되는 과목",
      "shared_concept": "공통 개념",
      "relationship": "어떻게 연결되는지 (한국어)",
      "synergy": "교차 학습 시너지 제안",
      "strength": "strong|moderate|weak"
    }}
  ],
  "recommended_cross_study": [
    {{
      "topic": "교차 학습 추천 주제",
      "subjects": ["과목1", "과목2"],
      "reason": "추천 이유"
    }}
  ]
}}

--- 현재 과목 ({current_subject}) 내용 ---
{current_text[:3000]}

--- 다른 과목 키워드 ---
{other_info}"""

    def find_connections(
        self,
        current_text: str,
        current_subject: str,
        other_subjects: dict[str, list[str]],
    ) -> Optional[dict]:
        """편의 메서드: 교차과목 연결 탐색."""
        return self.run({
            "current_text": current_text,
            "current_subject": current_subject,
            "other_subjects": other_subjects,
        })


def get_subject_keywords(config: dict) -> dict[str, list[str]]:
    """config에서 각 과목의 키워드 목록을 추출."""
    result = {}
    for subj_key, subj_cfg in config.get("subjects", {}).items():
        keywords = list(subj_cfg.get("pubmed_keywords", []))
        output_types = subj_cfg.get("output_types", [])
        keywords.extend(output_types)
        result[subj_key] = keywords
    return result
