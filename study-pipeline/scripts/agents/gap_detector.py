#!/usr/bin/env python3
"""gap_detector.py -- 누락 개념 감지 에이전트 (Ollama)."""

from __future__ import annotations

from typing import Optional

from agents.base_agent import BaseAgent


class GapDetector(BaseAgent):
    """강의노트 vs 교재/슬라이드를 비교하여 누락된 개념을 식별."""

    agent_name = "gap_detector"
    task_type = "classify"  # Ollama로 실행
    system_prompt = (
        "You are an educational gap analyzer. Compare lecture notes against textbook content "
        "to find missing concepts, incomplete explanations, and knowledge gaps. "
        "Focus on prerequisites and foundational knowledge that students might be missing. "
        "Always output valid JSON only."
    )

    def build_prompt(self, input_data: dict) -> Optional[str]:
        note_text = input_data.get("note_text", "")
        textbook_text = input_data.get("textbook_text", "")
        slides_text = input_data.get("slides_text", "")
        subject = input_data.get("subject", "")
        if not note_text:
            return None

        reference = textbook_text or slides_text or ""
        if not reference:
            return self._build_standalone_prompt(note_text, subject)

        return f"""다음 강의 필기와 교재/슬라이드 내용을 비교하여 학습 갭을 분석해주세요.

규칙:
- 교재에는 있지만 필기에 없는 핵심 개념 식별
- 필기에서 불완전하게 다룬 개념 식별
- 이해를 위해 필요한 선수지식/배경지식 식별
- 각 갭에 대한 보충 필요도(priority) 판정
- Output ONLY valid JSON.

출력 형식:
{{
  "subject": "{subject}",
  "gaps": [
    {{
      "concept": "누락/부족한 개념명",
      "type": "missing|incomplete|prerequisite|background",
      "priority": "high|medium|low",
      "description": "왜 이 개념이 필요한지 (한국어)",
      "in_textbook": true,
      "suggested_action": "보충 방법 제안"
    }}
  ],
  "coverage_score": 0.7,
  "summary": "전반적인 학습 갭 요약"
}}

--- 강의 필기 ---
{note_text[:4000]}

--- 교재/슬라이드 내용 ---
{reference[:4000]}"""

    def _build_standalone_prompt(self, note_text: str, subject: str) -> str:
        """교재 없이 필기만으로 갭 분석."""
        return f"""다음 강의 필기를 분석하여 학생이 추가로 학습해야 할 부분을 식별해주세요.

규칙:
- 설명이 부족하거나 약어/생략된 부분 식별
- 이해를 위해 필요한 선수지식 식별
- 심화 학습이 필요한 주제 식별
- Output ONLY valid JSON.

출력 형식:
{{
  "subject": "{subject}",
  "gaps": [
    {{
      "concept": "보충 필요 개념",
      "type": "incomplete|prerequisite|background",
      "priority": "high|medium|low",
      "description": "보충이 필요한 이유",
      "in_textbook": false,
      "suggested_action": "보충 방법 제안"
    }}
  ],
  "coverage_score": 0.5,
  "summary": "필기 분석 요약"
}}

--- 강의 필기 ---
{note_text[:5000]}"""

    def detect_gaps(
        self,
        note_text: str,
        subject: str = "",
        textbook_text: str = "",
        slides_text: str = "",
    ) -> Optional[dict]:
        """편의 메서드: 갭 감지 실행."""
        return self.run({
            "note_text": note_text,
            "subject": subject,
            "textbook_text": textbook_text,
            "slides_text": slides_text,
        })
