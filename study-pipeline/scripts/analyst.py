#!/usr/bin/env python3
"""analyst.py -- ChatGPT 기반 심화 분석 + 학습 계획 계층 (v3).

기능:
  1. 개념 갭 보충 콘텐츠 생성 (ChatGPT)
  2. 학습 계획 설계 (취약점 + 로컬 JSON 이력 기반)
  3. 교차과목 연결 심화 분석
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pipeline")

SCRIPT_DIR = Path(__file__).resolve().parent


class StudyAnalyst:
    """ChatGPT 기반 학습 분석가."""

    def __init__(self, config: dict):
        self.config = config
        from llm_router import LLMRouter
        self.router = LLMRouter(config)

    def generate_gap_supplements(
        self,
        gaps: list[dict],
        note_text: str,
        subject: str,
    ) -> str:
        """갭 감지 결과를 바탕으로 보충 콘텐츠 생성 (ChatGPT)."""
        if not gaps:
            return ""

        gaps_text = ""
        for i, g in enumerate(gaps[:5]):
            gaps_text += (
                f"\n{i+1}. [{g.get('priority', 'medium')}] {g.get('concept', '?')}\n"
                f"   유형: {g.get('type', '?')}\n"
                f"   설명: {g.get('description', '')}\n"
                f"   보충 방법: {g.get('suggested_action', '')}\n"
            )

        prompt = f"""다음 학습 갭 분석 결과를 바탕으로 보충 설명을 작성해주세요.

규칙:
- 한국어로 작성, 영문 과학 용어는 그대로 유지
- 각 개념에 대해 3-5문장의 명확한 설명
- 비유나 일상 예시를 활용
- 선수지식은 기초부터 간결하게 설명
- Markdown 형식, "## 개념 보충 설명" 섹션으로 작성
- 원래 노트 내용을 반복하지 말 것

--- 감지된 학습 갭 ---
{gaps_text}

--- 원본 노트 (참고) ---
{note_text[:3000]}
"""

        print("  → 갭 보충 콘텐츠 생성 중 (ChatGPT)...")
        result = self.router.generate(prompt, task_type="supplement")
        if result:
            print(f"    보충 콘텐츠: {len(result)}자")
        return result or ""

    def generate_study_plan(
        self,
        subject: str,
        weak_concepts: list[dict],
        due_reviews: list[dict],
        study_stats: dict,
        mastery_context: str,
    ) -> str:
        """학습 계획 생성 (ChatGPT + 로컬 학습 이력 데이터)."""
        weak_text = ""
        for c in weak_concepts[:10]:
            weak_text += f"  - {c['concept']}: mastery {c['mastery']:.0%}, priority {c['priority']}\n"

        due_text = ""
        for r in due_reviews[:10]:
            due_text += f"  - {r['concept']}: mastery {r['mastery']:.0%}, interval {r['interval']}일\n"

        stats = study_stats.get(subject, {})
        stats_text = (
            f"총 개념: {stats.get('total_concepts', 0)}개\n"
            f"마스터: {stats.get('mastered', 0)}개\n"
            f"취약: {stats.get('struggling', 0)}개\n"
            f"평균 mastery: {stats.get('avg_mastery', 0):.0%}"
        )

        template_path = SCRIPT_DIR / "templates" / "study_plan_prompt.txt"
        if template_path.exists():
            template = template_path.read_text(encoding="utf-8")
            prompt = template.format(
                subject=subject,
                stats_text=stats_text,
                weak_text=weak_text or "(없음)",
                due_text=due_text or "(없음)",
                mastery_text=mastery_context or "(아직 퀴즈 기록 없음)",
            )
        else:
            prompt = f"""학생의 학습 데이터를 바탕으로 맞춤 학습 계획을 작성해주세요.

규칙:
- 한국어로 작성, 영문 용어 유지
- Markdown 형식
- "## 학습 계획" 헤딩으로 시작
- 오늘 복습할 개념 (간격반복 기반) → 이번 주 목표 → 장기 계획
- 구체적인 학습 방법 제안 (교재 페이지, 문제 유형 등)
- 우선순위: 🔴 긴급 / 🟡 주의 / 🟢 양호
- 아래 mastery 상태 외 임의의 mastery 수치/등급을 만들지 말 것

--- 과목: {subject} ---

--- 학습 통계 ---
{stats_text}

--- 취약 개념 ---
{weak_text or "(없음)"}

--- 오늘 복습 대상 ---
{due_text or "(없음)"}

--- mastery 상태 (실데이터) ---
{mastery_context or "(아직 퀴즈 기록 없음)"}
"""

        print("  → 학습 계획 생성 중 (ChatGPT)...")
        result = self.router.generate(prompt, task_type="study_plan")
        if result:
            print(f"    학습 계획: {len(result)}자")
        return result or ""

    def analyze_cross_subject(
        self,
        connections: list[dict],
        current_subject: str,
    ) -> str:
        """교차과목 연결을 심화 분석하여 학습 가이드 생성 (ChatGPT)."""
        if not connections:
            return ""

        conn_text = ""
        for c in connections[:5]:
            conn_text += (
                f"\n- {c.get('other_subject', '?')}와의 연결:\n"
                f"  공통 개념: {c.get('shared_concept', '?')}\n"
                f"  관계: {c.get('relationship', '')}\n"
                f"  강도: {c.get('strength', 'moderate')}\n"
            )

        prompt = f"""다음 교차과목 연결 분석을 바탕으로 통합 학습 가이드를 작성해주세요.

규칙:
- 한국어로 작성, 영문 용어 유지
- Markdown 형식
- "## 교차과목 연결" 섹션으로 작성
- 각 연결에 대해 구체적인 학습 시너지 설명
- 실제 공부할 때 어떻게 활용할지 제안

현재 과목: {current_subject}

--- 발견된 연결 ---
{conn_text}
"""

        print("  → 교차과목 분석 중 (ChatGPT)...")
        result = self.router.generate(prompt, task_type="cross_subject")
        return result or ""

    def analyze_paper_relevance(
        self,
        papers: list[dict],
        note_text: str,
        subject: str,
    ) -> str:
        """논문과 수업 내용의 관련성 심화 분석 (ChatGPT)."""
        if not papers:
            return ""

        papers_text = ""
        for i, p in enumerate(papers[:3]):
            abstract = (p.get("abstract") or "")[:300]
            full_text_preview = (p.get("full_text") or "")[:500]
            papers_text += (
                f"\n### Paper {i+1}: {p.get('title', 'N/A')}\n"
                f"Authors: {p.get('authors', 'N/A')}\n"
                f"Year: {p.get('year', 'N/A')} | Citations: {p.get('citation_count', 0)}\n"
                f"Abstract: {abstract}\n"
            )
            if full_text_preview:
                papers_text += f"Full text preview: {full_text_preview}\n"

        prompt = f"""다음 학술 논문들이 현재 수업 내용과 어떻게 관련되는지 분석해주세요.

규칙:
- 한국어로 작성, 영문 용어 유지
- 각 논문이 수업의 어떤 부분을 확장하거나 보충하는지 설명
- 학생이 이 논문에서 꼭 알아야 할 핵심 1-2가지
- "## 관련 연구 심화 분석" 섹션으로 작성
- Markdown 형식

과목: {subject}

--- 수업 내용 ---
{note_text[:2000]}

--- 관련 논문 ---
{papers_text}
"""

        print("  → 논문 관련성 분석 중 (ChatGPT)...")
        result = self.router.generate(prompt, task_type="paper_analysis")
        return result or ""
