#!/usr/bin/env python3
"""classifier_agent.py -- 콘텐츠 유형/난이도 분류 에이전트 (Ollama)."""

from __future__ import annotations

from typing import Optional

from agents.base_agent import BaseAgent


class ClassifierAgent(BaseAgent):
    """콘텐츠를 유형별로 분류하고 난이도/시험출제 가능성을 판정."""

    agent_name = "classifier"
    task_type = "classify"
    system_prompt = (
        "You are a content classifier for university study materials. "
        "Analyze the given text and classify each section by type, difficulty, and exam likelihood. "
        "Always output valid JSON only."
    )

    def build_prompt(self, input_data: dict) -> Optional[str]:
        text = input_data.get("text", "")
        subject = input_data.get("subject", "")
        if not text:
            return None

        return f"""다음 학습 자료를 분석하여 섹션별로 분류해주세요.

규칙:
- 각 섹션의 유형을 판별: concept(개념), mechanism(메커니즘), example(사례), formula(공식), comparison(비교), definition(정의)
- 난이도 판별: easy, medium, hard
- 시험 출제 가능성 점수: 0.0~1.0
- Output ONLY valid JSON.

출력 형식:
{{
  "subject": "{subject}",
  "sections": [
    {{
      "title": "섹션 제목 또는 첫 줄",
      "type": "concept|mechanism|example|formula|comparison|definition",
      "difficulty": "easy|medium|hard",
      "exam_likelihood": 0.8,
      "key_concepts": ["concept1", "concept2"],
      "summary": "한 줄 요약"
    }}
  ],
  "overall_difficulty": "medium",
  "main_topics": ["topic1", "topic2"]
}}

--- 학습 자료 ---
{text[:6000]}"""

    def classify(self, text: str, subject: str = "") -> Optional[dict]:
        """편의 메서드: 텍스트를 분류."""
        return self.run({"text": text, "subject": subject})
