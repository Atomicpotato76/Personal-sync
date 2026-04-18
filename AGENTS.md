# AGENTS.md — Personal-sync 공통 규칙

## 저장소 구조
- `Self_Working_pipeline/` : Hermes 멀티에이전트 자동 개발/조사 파이프라인 (전용 AGENTS.md 있음)
- `daily_report_aggregator/` : 일일 리포트 수집기
- `pbl-router-v4/` : PBL 라우터 v4
- `study-pipeline/` : 학습 파이프라인

## 공통 작업 규칙

### 모델 버전 (필수)
- 코드에 LLM 모델명이 있으면 **반드시** 해당 provider 공식 문서를 검색하여 최신 모델인지 확인한다
  - OpenAI: https://developers.openai.com/api/docs/models
  - Anthropic: https://docs.anthropic.com/en/docs/about-claude/models
- 1개월 이상 지난 모델이 기본값이면 최신으로 교체한다
- 모델 변경 시 설정 파일 기본값과 환경변수 양쪽 모두 반영한다

### 코딩 규칙
- Python 타입 힌트를 항상 사용한다
- 한국어 주석 허용
- 외부 라이브러리 버전도 최신인지 확인 후 사용한다
- 테스트 후 커밋한다

### 파일 위치 규칙
- 프로젝트 전용 파일은 해당 프로젝트 폴더 안에 넣는다
- 루트에는 공통 설정 파일만 둔다
- 가이드 문서는 해당 프로젝트 폴더의 `docs/` 에 넣는다

### 검증 규칙
- API 키, 모델명, URL 등 외부 의존성은 반드시 웹 검색으로 현행 유효성을 확인한다
- "아마 맞을 것이다" 로 넘기지 않는다
- 확인 안 된 것은 확인 안 됐다고 명시한다

## 하위 프로젝트별 규칙
각 프로젝트 폴더의 `AGENTS.md`를 우선 적용한다. 이 파일과 충돌 시 하위 AGENTS.md가 우선한다.
