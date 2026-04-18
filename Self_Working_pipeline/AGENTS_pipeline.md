# AGENTS.md — Hermes 파이프라인 전용 규칙

## 프로젝트 개요
Hermes: Python 멀티에이전트 자동 개발/조사 파이프라인
Claude(설계/리뷰) ↔ GPT(실행) 핑퐁 루프 구조

## 프로젝트 구조
- `core/` : settings, state_machine, prompting, serialization, secret_scanner
- `services/adapters/` : anthropic_adapter, openai_adapter (LLM 연결)
- `services/planner/` : 계획 수립 에이전트
- `services/executor/` : 코드/조사 실행 에이전트
- `services/reviewer/` : 리뷰/팩트체크 에이전트
- `services/testing/` : 테스트/검증 실행
- `services/orchestrator/` : 전체 파이프라인 오케스트레이션 (핵심)
- `services/supervisor/` : 자동 승인 게이트 에이전트
- `services/memory/` : SQLite 기반 상태 저장 (models, db, service)
- `services/notifier/` : Discord 웹훅 알림
- `contracts/` : Pydantic 데이터 모델 (PlanBundle, RunRecord 등)
- `apps/cli/` : Typer CLI 인터페이스
- `apps/gui/` : GUI 인터페이스

## 작업 규칙
- contracts.models의 기존 Pydantic 모델은 변경하지 않는다
- orchestrator, state_machine, memory, supervisor의 구조를 유지한다
- 새 기능은 기존 패턴(mode 파라미터 분기)으로 추가한다
- Python 타입 힌트를 항상 사용한다
- 한국어 주석 허용
- 테스트 후 커밋한다

## 모델 버전 규칙 (최우선)
- settings.py에 모델명이 있으면 작업 전에 반드시 최신 모델인지 확인한다
- OpenAI 최신 확인: https://developers.openai.com/api/docs/models
- Anthropic 최신 확인: https://docs.anthropic.com/en/docs/about-claude/models
- 1개월 이상 지난 모델은 즉시 최신으로 교체한다
- 현재 사용 모델:
  - planner: claude-opus-4-6
  - executor: gpt-5.4 (환경변수 EXECUTOR_MODEL로 관리)
  - reviewer: claude-opus-4-6
  - supervisor: claude-opus-4-6

## 수정 가이드
이 프로젝트의 수정 지침은 `docs/` 폴더의 가이드 파일을 참조한다.
