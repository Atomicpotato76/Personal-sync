#!/usr/bin/env python3
"""collector_agent.py -- 관련 소스 자동 수집 에이전트 (Ollama)."""

from __future__ import annotations

from typing import Optional

from agents.base_agent import BaseAgent


class CollectorAgent(BaseAgent):
    """노트 주제에 맞는 관련 소스를 자동 수집하고 검색 키워드를 생성."""

    agent_name = "collector"
    task_type = "collect"
    system_prompt = (
        "You are a research assistant that identifies relevant sources for studying. "
        "Given lecture notes, extract key topics, suggest search keywords for papers, "
        "and identify which textbook chapters are most relevant. "
        "Always output valid JSON only."
    )

    def build_prompt(self, input_data: dict) -> Optional[str]:
        note_text = input_data.get("note_text", "")
        subject = input_data.get("subject", "")
        available_chapters = input_data.get("available_chapters", [])
        if not note_text:
            return None

        chapters_str = ", ".join(available_chapters) if available_chapters else "(없음)"

        return f"""다음 강의 필기를 분석하여 학습에 필요한 소스를 식별해주세요.

규칙:
- 핵심 주제 3-5개 추출
- 각 주제에 대한 PubMed/학술 검색 키워드 생성 (영문)
- 관련 교재 챕터 추천
- 추가 학습이 필요한 선수지식 식별
- Output ONLY valid JSON.

사용 가능한 교재 챕터: {chapters_str}

출력 형식:
{{
  "subject": "{subject}",
  "core_topics": ["topic1", "topic2"],
  "search_queries": [
    {{
      "topic": "주제",
      "query_en": "English search query for PubMed",
      "query_ko": "한국어 검색어"
    }}
  ],
  "recommended_chapters": ["ch4", "ch5"],
  "prerequisites": [
    {{
      "concept": "필요한 선수지식",
      "reason": "왜 필요한지"
    }}
  ]
}}

--- 강의 필기 ---
{note_text[:5000]}"""

    def collect(self, note_text: str, subject: str = "", available_chapters: list[str] | None = None) -> Optional[dict]:
        """편의 메서드: 소스 수집 계획 생성."""
        return self.run({
            "note_text": note_text,
            "subject": subject,
            "available_chapters": available_chapters or [],
        })
