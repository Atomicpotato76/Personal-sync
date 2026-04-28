# Study Pipeline v3 현재 개요

작성일: 2026-04-28  
대상: `study-pipeline`

이 문서는 파이썬을 깊게 모르는 사람도 현재 파이프라인의 기능 범위를 빠르게 이해할 수 있도록 정리한 문서다.

---

## 1. 이 프로젝트가 하는 일

Study Pipeline은 공부 노트, 교재 PDF, 강의 슬라이드, 선택형 논문 검색 결과를 합쳐 Markdown 정리본과 퀴즈를 만드는 학습 파이프라인이다.

현재 방향은 다음과 같다.

| 축 | 현재 결정 |
|---|---|
| 실행 방식 | CLI 또는 Streamlit GUI에서 수동 실행 |
| 출력 | Markdown only |
| 퀴즈 | 생성/승인/거절/복습 유지 |
| 학습 이력 | 로컬 JSON 유지 |
| 논문 보강 | 설정으로 켜고 끄는 선택 기능 |
| GUI | 유지 |
| 외부 router | 제거 |
| Claude Desktop MCP | 제거 |
| watcher/scheduler 자동화 | 제거 |
| PDF 출력 | 제거 |

---

## 2. 폴더 구조

```text
study-pipeline/
├── scripts/
│   ├── agents/
│   │   ├── classifier_agent.py
│   │   ├── gap_detector.py
│   │   ├── cross_subject.py
│   │   └── hermes_agent.py
│   ├── dashboard/
│   │   ├── app.py
│   │   ├── config_editor.py
│   │   ├── data_loader.py
│   │   ├── pipeline_runner.py
│   │   ├── quiz_manager.py
│   │   └── report_generator.py
│   ├── templates/
│   ├── config.yaml
│   ├── requirements.txt
│   ├── synthesize.py
│   ├── review.py
│   ├── hermes.py
│   ├── memory_manager.py
│   ├── quiz_store.py
│   ├── hermes_store.py
│   ├── llm_router.py
│   ├── path_utils.py
│   ├── marker_reader.py
│   ├── source_extractor.py
│   ├── paper_fetcher.py
│   ├── pubmed_client.py
│   ├── image_pipeline.py
│   ├── model_registry.py
│   └── env_utils.py
├── cache/
│   ├── hermes/
│   ├── papers/
│   ├── pubmed/
│   ├── text/
│   ├── textbook_quiz/
│   ├── images/
│   └── learning_history.json
├── queue/
├── approved/
├── rejected/
├── output/
│   └── md/
├── logs/
└── weak_concepts.json
```

---

## 3. 주요 스크립트별 역할

| 스크립트 | 역할 |
|---|---|
| `scripts/synthesize.py` | 노트/PDF/슬라이드 입력을 합쳐 Markdown 정리본과 퀴즈를 생성 |
| `scripts/llm_router.py` | LM Studio, ChatGPT, Claude fallback 라우팅 |
| `scripts/memory_manager.py` | 로컬 JSON 학습 이력과 간격반복 상태 저장 |
| `scripts/review.py` | 퀴즈 복습 CLI |
| `scripts/hermes.py` | 공부 일정 CLI |
| `scripts/dashboard/app.py` | Streamlit GUI |
| `scripts/dashboard/report_generator.py` | Markdown 학습 리포트 생성 |
| `scripts/paper_fetcher.py` | Semantic Scholar 기반 논문 보강 |
| `scripts/pubmed_client.py` | PubMed 논문 검색/요약 보강 |
| `scripts/source_extractor.py` | 노트, 교재, 슬라이드 자료 통합 |
| `scripts/marker_reader.py` | PDF 텍스트 추출 fallback |

---

## 4. 데이터 흐름

```text
[입력]
노트 Markdown, 교재 PDF, 강의 PDF/PPTX
선택: Semantic Scholar / PubMed 논문 검색
        |
        v
[실행]
CLI 또는 Streamlit GUI에서 synthesize.py 호출
        |
        v
[처리]
1. 소스 수집
2. PDF/슬라이드 텍스트 추출
3. 노트 분류와 학습 공백 감지
4. 과목 간 연결 분석
5. 선택형 논문 보강
6. LLM 종합
7. 보충 설명/분석 섹션 추가
8. 퀴즈 생성
9. Markdown 저장
10. 로컬 JSON 학습 이력 갱신
        |
        v
[출력]
output/md/                 Markdown 정리본
queue/                     검토 대기 퀴즈
weak_concepts.json          개념별 숙련도
cache/learning_history.json 학습 이벤트 이력
cache/hermes/               공부 일정 JSON
```

---

## 5. LLM 사용 방식

| Provider | 용도 |
|---|---|
| LM Studio | 로컬 초안, 분류, 반복 작업 |
| ChatGPT | 분석, 보충 설명, 과목 간 연결 |
| Claude | 심화 합성, 퀴즈 생성, 고난도 설명 |

외부 router는 사용하지 않는다. `scripts/config.yaml`의 `llm.routing`과 각 provider 설정으로 작업별 우선순위를 조정한다.

---

## 6. 논문 보강

논문 보강은 유지하지만 기본값은 꺼져 있다.

| 설정 | 의미 |
|---|---|
| `papers.enabled` | Semantic Scholar 기반 논문 보강 |
| `pubmed.enabled` | PubMed 기반 생의학 논문 보강 |

GUI에서도 켜고 끌 수 있다. 논문 보강을 끄면 파이프라인은 노트, 교재, 슬라이드 중심으로 정리본과 퀴즈를 만든다.

---

## 7. 학습 이력과 복습

학습 이력은 로컬 JSON으로 저장한다.

| 파일 | 역할 |
|---|---|
| `weak_concepts.json` | 개념별 숙련도와 복습 예정일 |
| `cache/learning_history.json` | 최근 학습 이벤트 |
| `queue/*.json` | 검토 대기 퀴즈 |
| `approved/*.json` | 승인된 퀴즈 |
| `rejected/*.json` | 거절된 퀴즈 |

SM-2/FSRS 기반 복습 로직과 Hermes 일정 생성은 유지한다.

---

## 8. 실행 방법

### 설치

```powershell
pip install -r scripts/requirements.txt
pip install -r scripts/dashboard/requirements.txt
```

### 단일 노트 처리

```powershell
python scripts/synthesize.py "노트파일.md"
```

### PDF만으로 처리

```powershell
python scripts/synthesize.py --pdf-only "교재.pdf" --subject organic_chem
```

### 웹 대시보드

```powershell
run_dashboard.bat
```

또는:

```powershell
streamlit run scripts/dashboard/app.py
```

### 퀴즈 복습

```powershell
python scripts/review.py do
```

### 일정 생성

```powershell
python scripts/hermes.py plan-day
python scripts/hermes.py plan-week
```

---

## 9. 설정 파일

핵심 설정은 `scripts/config.yaml`에 있다.

| 섹션 | 내용 |
|---|---|
| `paths` 계열 | Vault, pipeline, notes 경로 |
| `llm` | LM Studio, ChatGPT, Claude 설정 |
| `papers` | Semantic Scholar 논문 보강 설정 |
| `pubmed` | PubMed 보강 설정 |
| `mem0` | 현재는 `enabled: false`, `mode: local_json` |
| `output` | 현재는 Markdown 출력만 사용 |
| `subjects` | 과목별 노트/교재/슬라이드/프롬프트 설정 |

비밀 키는 `.env` 또는 시스템 환경변수로 관리한다. 키 값은 문서나 로그에 직접 적지 않는다.

| 환경변수 | 용도 |
|---|---|
| `OPENAI_API_KEY` | ChatGPT API |
| `ANTHROPIC_API_KEY` | Claude API |
| `NCBI_EMAIL` | PubMed 요청 식별 |
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar 선택 키 |

---

## 10. 한눈에 보는 현재 구조

```text
[노트/PDF/슬라이드]
        |
        v
  synthesize.py
        |
        +--> LM Studio / ChatGPT / Claude
        |
        +--> 선택형 논문 보강
        |
        +--> output/md/
        |
        +--> queue/ 퀴즈
        |
        +--> local JSON 학습 이력
        |
        v
  review.py / dashboard / hermes.py
```
