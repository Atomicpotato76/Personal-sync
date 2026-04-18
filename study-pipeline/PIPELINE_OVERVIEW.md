# Study Pipeline v3 — 프로젝트 전체 개요

> 작성일: 2026-04-17  
> 파이썬을 모르는 사람도 이해할 수 있도록 작성되었습니다.

---

## 1. 이 프로젝트가 하는 일

**Study Pipeline**은 Obsidian에 작성한 공부 노트를 자동으로 받아서, 교재·강의자료·논문과 합쳐 "정리된 요약본"과 "퀴즈"를 만들어주는 AI 기반 학습 자동화 시스템입니다. 노트를 저장하는 순간 파이프라인이 실행되고, 로컬 LLM(LM Studio) → ChatGPT → Claude 순서로 작업을 분산 처리합니다. 생성된 퀴즈는 SM-2 / FSRS 간격반복 알고리즘으로 복습 일정을 자동 조율하고, Hermes 스케줄러가 시험 날짜·에너지 수준·약점 개념을 고려해 하루/주간 공부 계획을 짜줍니다. 결과물은 웹 대시보드(Streamlit), CLI, 또는 Claude Desktop MCP 채팅으로 확인할 수 있습니다.

---

## 2. 폴더 구조

```
study-pipeline/
│
├── scripts/                         # 핵심 코드 모음
│   ├── agents/                      # AI 에이전트들
│   │   ├── base_agent.py            # 모든 에이전트의 공통 기반
│   │   ├── classifier_agent.py      # 노트 섹션 분류
│   │   ├── gap_detector.py          # 학습 공백 감지
│   │   ├── cross_subject.py         # 과목 간 연결 탐색
│   │   └── hermes_agent.py          # 공부 일정 계획 에이전트
│   │
│   ├── mcp_tools/                   # Claude Desktop 연동 도구
│   │   ├── concepts.py              # 약점 개념·복습 예정 목록
│   │   ├── explain.py               # 개념 설명 생성
│   │   ├── history.py               # 퀴즈 이력·주간 요약
│   │   ├── notes.py                 # 공부 노트 검색
│   │   ├── papers.py                # 캐시된 논문 조회
│   │   ├── quiz.py                  # 퀴즈 생성·결과 기록
│   │   ├── schedule.py              # Hermes 일정 연동
│   │   └── textbook.py              # 교재 내용 불러오기
│   │
│   ├── dashboard/                   # 웹 대시보드 (Streamlit)
│   │   ├── app.py                   # 대시보드 메인
│   │   ├── config_editor.py         # config.yaml 편집 UI
│   │   ├── data_loader.py           # 데이터 불러오기
│   │   ├── pipeline_runner.py       # 수동 파이프라인 실행
│   │   ├── quiz_manager.py          # 퀴즈 승인/거절
│   │   ├── report_generator.py      # 학습 리포트 생성
│   │   └── change_monitor.py        # 파일 변경 모니터링
│   │
│   ├── templates/                   # LLM 프롬프트 템플릿
│   │   ├── organic_chem.txt         # 유기화학 합성 프롬프트
│   │   ├── genomics_ai.txt          # 유전체학 프롬프트
│   │   ├── mycology.txt             # 균류학 프롬프트
│   │   ├── pubmed_prompt.txt        # PubMed 논문 요약 프롬프트
│   │   └── synthesis_prompt.txt     # 범용 합성 프롬프트
│   │
│   ├── config.yaml                  # 프로젝트 중앙 설정 파일
│   ├── requirements.txt             # 파이썬 라이브러리 목록
│   │
│   ├── synthesize.py                # ★ 10단계 파이프라인 총괄
│   ├── watcher.py                   # Obsidian 파일 변경 감지
│   ├── review.py                    # 퀴즈 복습 CLI
│   ├── hermes.py                    # 일정 관리 CLI
│   ├── mcp_server.py                # Claude Desktop MCP 서버
│   ├── scheduler.py                 # Windows 작업 스케줄러 등록
│   ├── memory_manager.py            # 학습 기억 + 간격반복 (SM-2/FSRS)
│   ├── quiz_store.py                # 퀴즈 파일 입출력
│   ├── hermes_store.py              # 일정 데이터 저장
│   ├── llm_router.py                # 3-단계 LLM 라우팅
│   ├── path_utils.py                # 경로 관리
│   ├── marker_reader.py             # PDF 파싱
│   ├── source_extractor.py          # 교재·슬라이드·노트 통합
│   ├── paper_fetcher.py             # 논문 검색·수집
│   ├── pubmed_client.py             # PubMed API 연동
│   ├── image_pipeline.py            # PDF/슬라이드 이미지 추출
│   ├── model_registry.py            # API 모델 탐색
│   └── env_utils.py                 # 환경변수 유틸리티
│
├── cache/                           # 자동 생성 캐시 (건드릴 필요 없음)
│   ├── hermes/
│   │   ├── exam_calendar.json       # 시험·마감 일정
│   │   ├── schedule_profile.json    # 하루 시간대별 에너지 설정
│   │   ├── study_schedule.json      # 생성된 공부 계획
│   │   └── hermes_state.json        # Hermes 이력
│   ├── papers/                      # 수집된 논문 캐시
│   ├── pubmed/                      # PubMed 검색 결과
│   ├── text/                        # 교재/슬라이드 텍스트 추출본
│   ├── learning_history.json        # 전체 학습 기록
│   ├── note_index.json              # 노트 메타데이터 인덱스
│   └── images/                      # 추출된 이미지
│
├── queue/                           # 검토 대기 중인 퀴즈
├── approved/                        # 승인된 퀴즈
├── rejected/                        # 거절된 퀴즈
├── output/
│   ├── md/                          # AI가 생성한 요약 노트 (Markdown)
│   └── pdf/                         # AI가 생성한 요약 노트 (PDF)
│
└── weak_concepts.json               # 개념별 숙련도 추적 (SM-2 데이터)
```

---

## 3. 주요 스크립트별 역할

| 스크립트 | 한마디 요약 | 담당 역할 |
|---------|-----------|---------|
| `synthesize.py` | **파이프라인 총지휘자** | 노트 한 개를 받아 10단계 처리 후 요약·퀴즈 생성 |
| `watcher.py` | **자동 감시자** | Obsidian 폴더를 실시간 감시 → 변경 감지 시 synthesize 자동 실행 |
| `llm_router.py` | **AI 교통 정리** | 작업 종류에 따라 LM Studio → ChatGPT → Claude 중 최적 LLM 선택 |
| `memory_manager.py` | **학습 기억 창고** | 퀴즈 결과 저장, 다음 복습 날짜 계산 (SM-2/FSRS 알고리즘) |
| `hermes_agent.py` | **스케줄 기획자** | 약점·시험일·에너지 수준을 고려해 하루/주간 공부 블록 생성 |
| `mcp_server.py` | **Claude Desktop 다리** | Claude와 채팅하면서 공부 데이터 조회·퀴즈·일정 확인 가능 |
| `dashboard/app.py` | **웹 대시보드** | 브라우저에서 숙련도 그래프, 퀴즈 관리, 설정 편집 |
| `review.py` | **퀴즈 복습 CLI** | 터미널에서 퀴즈를 풀고 결과를 기록 |
| `hermes.py` | **일정 CLI** | 터미널에서 하루/주간 계획 생성, 시험 추가 |
| `scheduler.py` | **자동 실행 등록** | Windows 작업 스케줄러에 매일 밤 자동 실행 등록 |
| `paper_fetcher.py` | **논문 수집기** | Semantic Scholar + PubMed에서 관련 논문 자동 검색·저장 |
| `marker_reader.py` | **PDF 해석기** | 교재·슬라이드 PDF를 텍스트로 변환 (3중 폴백 방식) |
| `source_extractor.py` | **자료 통합기** | 노트·교재·슬라이드를 하나의 입력으로 묶음 |

---

## 4. 데이터 흐름 (입력 → 처리 → 출력)

```
[입력]
Obsidian 공부 노트 (.md 파일)
교재 PDF / 강의 슬라이드 (.pdf, .pptx)
학술 논문 (Semantic Scholar / PubMed 자동 수집)
        │
        ▼
[감지] watcher.py
  → Obsidian 폴더를 실시간 감시
  → 노트 저장 시 synthesize.py 자동 호출
        │
        ▼
[처리] synthesize.py (10단계 파이프라인)
  1단계  source_extractor  →  노트 + 교재 + 슬라이드 텍스트 통합
  2단계  marker_reader     →  PDF 파싱 가능 여부 확인
  3단계  classifier_agent  →  LM Studio로 노트 섹션 분류 + 학습 공백 감지
  4단계  cross_subject     →  ChatGPT로 과목 간 개념 연결 탐색
  5단계  paper_fetcher     →  Semantic Scholar + PubMed 논문 검색
  6단계  LLM 합성          →  (LM Studio 초안 → Claude 심화) 또는 1회 합성
  7단계  분석 섹션 추가    →  ChatGPT로 공백 보완 + 논문 연결 섹션 작성
  8단계  공부 계획 섹션   →  약점·복습 예정·추천 집중 영역 자동 삽입
  9단계  퀴즈 생성         →  교재 문제 추출 + Claude로 새 퀴즈 생성
  10단계 결과 저장         →  MD/PDF 저장, 학습 기억 갱신, 일정 재계획
        │
        ▼
[출력]
output/md/          → 요약 노트 (Markdown)
output/pdf/         → 요약 노트 (PDF)
queue/              → 검토 대기 퀴즈
weak_concepts.json  → 개념별 숙련도 업데이트
learning_history.json → 학습 전체 기록 누적
cache/hermes/       → 갱신된 공부 일정
        │
        ▼
[복습 루프]
review.py / 대시보드 / Claude Desktop
  → 퀴즈 풀기 → 결과 기록
  → SM-2/FSRS 알고리즘으로 다음 복습 날짜 자동 계산
  → Hermes가 새 공부 블록 재생성
```

---

## 5. 외부 의존성 (API 및 라이브러리)

### 외부 API 연결

| 서비스 | 용도 | 비고 |
|-------|------|------|
| **LM Studio** (로컬) | 분류·초안 작성 등 반복 작업 | 내 PC/데스크탑에서 직접 실행, 비용 무료 |
| **OpenAI (ChatGPT)** | 과목 간 분석, 논문 요약 등 중간 난이도 작업 | API 키 필요 |
| **Anthropic (Claude)** | 심화 합성, 퀴즈 생성 등 고난이도 작업 | API 키 필요 |
| **Semantic Scholar** | 학술 논문 검색 | 무료 API (키 선택 사항) |
| **PubMed (NCBI Entrez)** | 생의학 논문 검색 | 무료 (이메일 등록 필요) |
| **Chroma (벡터 DB)** | mem0 학습 기억 저장 | 원격 PC에 Tailscale으로 연결 (선택 사항) |

### 주요 파이썬 라이브러리

| 분류 | 라이브러리 | 용도 |
|-----|-----------|------|
| AI/LLM | `anthropic`, `openai` | Claude, ChatGPT API 연동 |
| PDF 처리 | `marker-pdf`, `pdfplumber`, `pymupdf` | PDF → 텍스트 변환 (3중 폴백) |
| 간격반복 | `fsrs` | FSRS 알고리즘 (SM-2는 자체 구현) |
| 학습 기억 | `mem0ai` | 벡터 기반 장기 학습 기억 |
| 논문 검색 | `semanticscholar`, `biopython` | 학술 논문 수집 |
| 웹 대시보드 | `streamlit`, `plotly`, `pandas` | 시각화 대시보드 |
| 파일 감시 | `watchdog` | Obsidian 폴더 실시간 감시 |
| 기타 | `pyyaml`, `requests`, `Pillow`, `reportlab` | 설정·요청·이미지·PDF 생성 |

---

## 6. 실행 방법 (순서대로)

### 최초 설치

```bash
# 1. 라이브러리 설치
pip install -r scripts/requirements.txt

# 2. 환경변수 설정 (.env 파일 또는 시스템 환경변수)
#    아래 '설정 파일' 섹션 참고

# 3. config.yaml 에서 과목·폴더 경로 설정
#    scripts/config.yaml 직접 편집하거나 대시보드 Config Editor 탭 사용
```

### 자동 실행 (매일 밤 자동 처리)

```bash
# Windows 작업 스케줄러에 등록 (한 번만 실행)
python scripts/scheduler.py register

# 즉시 수동 실행
python scripts/scheduler.py run-now
```

### 파일 변경 실시간 감시

```bash
# Obsidian 저장 시 자동으로 파이프라인 실행
python scripts/watcher.py
```

### 특정 노트 수동 처리

```bash
# 대시보드 > Pipeline Runner 탭 사용 (GUI)
streamlit run scripts/dashboard/app.py

# 또는 CLI
python scripts/synthesize.py --note "노트파일명.md" --subject organic_chem
```

### 퀴즈 복습

```bash
# CLI로 퀴즈 풀기
python scripts/review.py do

# 퀴즈 목록 보기
python scripts/review.py list

# 대시보드 > Quiz Manager 탭 사용 가능
streamlit run scripts/dashboard/app.py
```

### 공부 일정 관리

```bash
# 오늘 일정 생성
python scripts/hermes.py plan-day

# 이번 주 일정 생성
python scripts/hermes.py plan-week

# 시험 일정 추가
python scripts/hermes.py add-exam --subject organic_chem --date 2026-05-10 --title "중간고사"

# 일정 현황 확인
python scripts/hermes.py status
```

### Claude Desktop MCP 연동

```bash
# 1. MCP 서버 시작
python scripts/mcp_server.py

# 2. Claude Desktop 설정 파일에 등록
#    %APPDATA%\Claude\claude_desktop_config.json 에 서버 경로 추가

# 3. Claude Desktop에서 채팅으로 공부 데이터 조회·퀴즈·일정 확인 가능
```

### 웹 대시보드

```bash
streamlit run scripts/dashboard/app.py
# 브라우저에서 http://localhost:8501 접속
```

---

## 7. 설정 파일들

### `scripts/config.yaml` — 프로젝트 중앙 설정

모든 동작을 제어하는 핵심 설정 파일입니다. 직접 편집하거나 대시보드 Config Editor 탭을 사용하세요.

| 섹션 | 내용 |
|-----|------|
| `scheduler` | 간격반복 알고리즘 선택 (`sm2` 또는 `fsrs`) |
| `interleaving_mode` | 혼동 개념 교차 배치 방식 (`off` / `soft` / `strict`) |
| `energy_profile` | 시간대별 에너지 수준 (`19:00: high` 등) |
| `llm.primary/secondary/tertiary` | LLM 우선순위 (`lmstudio` → `chatgpt` → `claude`) |
| `llm.lmstudio` | LM Studio 서버 주소, 모델명, 타임아웃 |
| `llm.chatgpt` | ChatGPT 모델명, 최대 토큰 수 |
| `llm.claude` | Claude 모델명, thinking 예산 |
| `llm.routing` | 어떤 작업을 어떤 LLM에 보낼지 분류 목록 |
| `mem0` | 벡터 기억 저장소 설정 (Chroma 서버 주소 등) |
| `marker` | PDF 파싱 설정 |
| `papers` | 논문 수집 설정 (최대 수집 수 등) |
| `pubmed` | PubMed 검색 범위 설정 |
| `subjects` | 과목별 설정: Obsidian 폴더 경로, 교재 파일, 슬라이드 폴더, 프롬프트 템플릿, PubMed 검색어 |

### `.env` 또는 시스템 환경변수 — 비밀 키 모음

> **⚠️ 이 파일에 실제 키 값을 직접 입력하고, 절대 외부에 공유하지 마세요.**

| 환경변수명 | 용도 |
|----------|------|
| `OPENAI_API_KEY` | ChatGPT API 사용을 위한 인증 키 |
| `ANTHROPIC_API_KEY` | Claude API 사용을 위한 인증 키 |
| `NCBI_EMAIL` | PubMed 검색 시 NCBI에 등록할 이메일 (무료) |
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar 논문 검색 키 (선택 사항) |
| `MEM0_API_KEY` | mem0 클라우드 사용 시 필요한 키 (선택 사항) |

### `cache/hermes/schedule_profile.json` — Hermes 일정 프로파일

공부 가능한 시간대, 하루 최대 공부 시간, 과목별 우선순위 등을 저장합니다.

### `cache/hermes/exam_calendar.json` — 시험·마감 일정

`hermes.py add-exam` 명령으로 추가된 시험 날짜와 과제 마감일 목록입니다.

---

## 한눈에 보는 전체 구조

```
[Obsidian 노트 저장]
       ↓
  watcher.py 감지
       ↓
  synthesize.py (10단계)
  ┌────────────────────────────────┐
  │ LM Studio (로컬, 무료)         │  ← 분류, 초안
  │ ChatGPT (API)                 │  ← 분석, 연결
  │ Claude (API)                  │  ← 심화 합성, 퀴즈
  └────────────────────────────────┘
       ↓                    ↓
  output/ (요약·PDF)   queue/ (퀴즈)
                            ↓
                    [복습 인터페이스 3종]
                    ① review.py (터미널)
                    ② 대시보드 (브라우저)
                    ③ Claude Desktop (채팅)
                            ↓
                    SM-2/FSRS 간격반복
                            ↓
                    Hermes 일정 재계획
```
