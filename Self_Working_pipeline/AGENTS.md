# AGENTS.md

## 프로젝트 개요
Hermes: Python 멀티에이전트 자동 개발/조사 파이프라인

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

## 수정 가이드
이 repo의 `hermes_fix_guide.md`에 상세한 수정 지침이 있다.
모든 수정은 해당 가이드를 따른다.
