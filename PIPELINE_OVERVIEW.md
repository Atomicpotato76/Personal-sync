# AI_projects — 전체 파이프라인 개요

> 파이썬을 잘 모르는 사람도 읽을 수 있도록 작성했습니다.  
> 마지막 업데이트: 2026-04-17

---

## 1. 이 프로젝트가 하는 일

`AI_projects` 폴더는 **4개의 독립적인 AI 자동화 프로젝트**로 구성됩니다. 각각 ① 금융 뉴스·리서치를 매일 자동으로 수집해 보고서로 정리하고, ② 질문 내용에 따라 적합한 AI 모델(로컬 LLM, Claude, GPT)로 자동 분배하는 라우터를 운영하며, ③ 소프트웨어 개발 작업을 AI 에이전트들이 계획→구현→검토→패키징까지 자동으로 처리하고, ④ 유기화학·유전체학·균학 3개 과목의 공부를 AI가 퀴즈 생성·복습 스케줄·오답 분석까지 자동화해주는 학습 파이프라인을 포함합니다. 모든 프로젝트는 Tailscale VPN으로 연결된 로컬 LLM 서버(LM Studio)와 Claude, GPT 클라우드 API를 함께 사용합니다.

---

## 2. 폴더 구조

```
AI_projects/
│
├── daily_report_aggregator/        ← 금융 뉴스 자동 수집·보고서 생성
│   ├── main.py                     (실행 진입점)
│   ├── config.py                   (설정값)
│   ├── collectors/
│   │   ├── gmail_reader.py         (Gmail에서 이메일 수집)
│   │   ├── yahoo_finance.py        (야후 파이낸스 시세·기사)
│   │   ├── naver_research.py       (네이버 증권 리서치 리포트)
│   │   ├── seeking_alpha.py        (Seeking Alpha 뉴스)
│   │   └── http_client.py          (공통 HTTP + 캐시 + 크롤링 보조)
│   ├── processor/
│   │   └── summarizer.py           (수집 데이터 → Markdown 보고서)
│   ├── .cache/                     (중복 요청 방지용 캐시)
│   └── output/reports/YYYY-MM-DD/  (날짜별 완성 보고서)
│
├── pbl-router-v4/                  ← AI 모델 자동 라우팅 서버
│   ├── router_v4.py                (핵심 라우팅 엔진)
│   ├── router_server.py            (FastAPI HTTP 서버)
│   ├── client.py                   (외부에서 호출할 때 쓰는 클라이언트)
│   ├── presets/                    (모델별 역할 설정 파일들 *.preset.json)
│   │   ├── hermes.preset.json      (로컬 Gemma — 일반 대화)
│   │   ├── lecture_parser.preset.json  (슬라이드 분석)
│   │   ├── domain_expert.preset.json   (Claude — 유전체학 전문)
│   │   ├── critic.preset.json      (GPT — 검토·비판)
│   │   └── formatter.preset.json   (문서 정리·형식화)
│   ├── profiles/                   (모드별 활성 프리셋 묶음 *.profile.json)
│   │   ├── study.profile.json      (공부 모드: hermes + lecture_parser)
│   │   ├── work.profile.json       (작업 모드: hermes + domain_expert + critic)
│   │   └── full.profile.json       (전체 프리셋 활성)
│   └── .env                        (API 키 등 환경변수)
│
├── Self_Working_pipeline/          ← AI가 소프트웨어를 자동으로 개발
│   ├── apps/
│   │   ├── cli/main.py             (터미널 명령어 인터페이스)
│   │   └── gui/main.py             (데스크톱 GUI)
│   ├── core/
│   │   ├── state_machine.py        (단계별 상태 관리)
│   │   ├── settings.py             (전체 설정값)
│   │   ├── prompting.py            (AI 프롬프트 구성)
│   │   ├── serialization.py        (파일 저장·불러오기)
│   │   └── secret_scanner.py       (환경변수 누락 체크)
│   ├── contracts/
│   │   └── models.py               (데이터 구조 정의)
│   ├── plans/<run_id>/             (기획 문서 저장)
│   ├── outputs/<run_id>/           (생성된 코드·보고서·패키지)
│   └── .env                        (API 키 등 환경변수)
│
└── study-pipeline/                 ← AI 기반 학습 자동화
    ├── scripts/
    │   ├── generate.py             (노트 → 퀴즈 자동 생성)
    │   ├── review.py               (퀴즈 복습 실행)
    │   ├── synthesize.py           (노트 → 정리 요약 생성)
    │   ├── memory_manager.py       (간격 반복·숙달도 추적)
    │   ├── hermes_agent.py         (오늘의 공부 스케줄 생성)
    │   ├── hermes_store.py         (스케줄 데이터 저장)
    │   ├── quiz_store.py           (퀴즈 메타데이터 관리)
    │   ├── watcher.py              (노트 변경 감지 → 자동 퀴즈 생성)
    │   ├── scheduler.py            (Windows 작업 스케줄러 연동)
    │   ├── record_exam.py          (시험 성적 기록)
    │   ├── exam_postmortem.py      (시험 오답 원인 분석)
    │   ├── competency_map.py       (과목별 숙달도 시각화)
    │   ├── paper_fetcher.py        (PubMed 논문 자동 검색·캐시)
    │   ├── marker_reader.py        (PDF → 텍스트 변환)
    │   └── llm_router.py           (pbl-router-v4 연동)
    ├── config.yaml                 (전체 동작 설정)
    ├── cache/                      (논문·임베딩·학습 이력 캐시)
    ├── queue/                      (생성된 퀴즈 대기열)
    ├── templates/                  (과목별 AI 프롬프트 템플릿)
    ├── tests/                      (자동화 테스트 40+개)
    └── logs/                       (실행 로그)
```

---

## 3. 주요 스크립트별 역할

### daily_report_aggregator

| 파일 | 하는 일 |
|------|---------|
| `main.py` | 전체 수집 과정을 시작하는 진입점. 이 파일 하나를 실행하면 아래 모든 collector가 순서대로 돌아감 |
| `collectors/gmail_reader.py` | Gmail에서 NYT Briefing, Yahoo Morning Brief 등 구독 이메일을 읽어옴 (OAuth 인증 사용) |
| `collectors/yahoo_finance.py` | S&P 500, NASDAQ, DOW, 비트코인, 원자재 등 시장 지수를 가져오고, 관련 기사에서 주가 변동 정보 추출 |
| `collectors/naver_research.py` | 네이버 증권에서 국내 증권사 리서치 리포트 목록을 가져오고, PDF를 내려받아 텍스트로 변환 |
| `collectors/seeking_alpha.py` | Seeking Alpha의 마켓 뉴스 수집 |
| `collectors/http_client.py` | 웹 요청 전담 모듈. 캐시로 중복 요청을 막고, 차단당했을 때는 Playwright(헤드리스 브라우저)로 우회 |
| `processor/summarizer.py` | 수집된 모든 데이터를 날짜별 Markdown 보고서 파일로 정리 |

### pbl-router-v4

| 파일 | 하는 일 |
|------|---------|
| `router_v4.py` | 핵심 엔진. 입력된 질문의 키워드를 분석해 어떤 AI 프리셋(모델+역할)으로 보낼지 결정 |
| `router_server.py` | HTTP API 서버. 외부 앱이 `/chat` 엔드포인트로 요청을 보내면 라우터가 처리해서 답변 반환 |
| `client.py` | 다른 스크립트에서 라우터 서버를 쉽게 호출하기 위한 헬퍼 |

### Self_Working_pipeline

| 파일 | 하는 일 |
|------|---------|
| `core/state_machine.py` | 작업이 지금 어느 단계(기획→승인→실행→검토→패키징)에 있는지 추적하고 단계 전환을 관리 |
| `contracts/models.py` | 각 단계에서 주고받는 데이터 구조 정의 (기획서, 아키텍처 스펙, 실행 결과, 검토 보고서 등) |
| `core/prompting.py` | 각 단계별로 AI에게 보낼 프롬프트를 조합해서 만드는 모듈 |
| `apps/cli/main.py` | 터미널에서 `plan`, `approve`, `run`, `status` 같은 명령어로 파이프라인을 제어 |

### study-pipeline

| 파일 | 하는 일 |
|------|---------|
| `generate.py` | Obsidian 노트를 읽어 AI가 퀴즈(문제+정답)를 만들고 queue에 저장 |
| `review.py` | 저장된 퀴즈를 꺼내 대화형으로 복습. 정답 여부·자신감 점수·오답 유형 기록 |
| `memory_manager.py` | SM-2 또는 FSRS 알고리즘으로 개념별 숙달도와 다음 복습일을 계산 |
| `hermes_agent.py` | 오늘의 에너지 수준(아침/오후/저녁), 남은 시간, 개념 우선순위를 고려해 공부 스케줄을 짬 |
| `synthesize.py` | 노트를 10단계로 분석해 핵심 개념 추출→Q&A→메커니즘 다이어그램→과목 간 연결→논문 인용→최종 요약까지 자동 생성 |
| `watcher.py` | Obsidian 폴더를 실시간으로 감시. 새 노트나 변경이 생기면 자동으로 퀴즈 생성 트리거 |
| `record_exam.py` | 실제 시험이나 모의시험 점수를 기록. 시험은 2배, 모의고사는 1.5배 가중치 적용 |
| `exam_postmortem.py` | 시험 후 오답 원인을 분석해 다음 주에 집중할 상위 3개 약점 개념을 추천 |
| `paper_fetcher.py` | PubMed와 Semantic Scholar에서 관련 논문을 자동 검색하고 30일 캐시에 저장 |

---

## 4. 데이터 흐름

### daily_report_aggregator

```
[Gmail 이메일]         ┐
[야후 파이낸스 API]     ├─→ http_client.py (캐시 적용) ─→ summarizer.py ─→ output/reports/YYYY-MM-DD/*.md
[네이버 증권 웹]        │                                     ↑
[Seeking Alpha 웹]    ┘                              데이터 모델(dataclass)로 통일
```

### pbl-router-v4

```
사용자 질문 텍스트
      ↓
router_v4.py: 키워드 점수 계산 → 로컬 Gemma로 분류(확신 낮을 때)
      ↓
매칭된 preset.json 로드 (시스템 프롬프트 + 파라미터)
      ↓
[로컬 LM Studio] or [Claude API] or [GPT API]
      ↓
응답 텍스트 → 세션 히스토리 저장 → 클라이언트에 반환
```

### Self_Working_pipeline

```
사용자 요청(텍스트 파일)
      ↓ plan
[Claude Opus] 기획서 + 아키텍처 스펙 + API 계약서 생성
      ↓ approve (사람이 승인)
[GPT-4o] 코드 실행 (git worktree에 파일 생성)
      ↓
[Claude Opus] 코드 리뷰 + 테스트 실행
      ↓ merge_approved (사람이 승인)
최종 패키지 outputs/<run_id>/package/ 에 저장
```

### study-pipeline

```
[Obsidian 노트 .md 파일]
      ↓ watcher.py 감지 or 수동 실행
generate.py: 노트 → LLM → 퀴즈 JSON → queue/ 폴더
      ↓
review.py: 퀴즈 출제 → 사용자 답변 → 정오답 기록
      ↓
memory_manager.py: SM-2/FSRS 계산 → 다음 복습일 업데이트
      ↓
hermes_agent.py: 오늘 스케줄 생성 (난이도 × 에너지 매칭)
      ↓
[시험 후] exam_postmortem.py → 약점 개념 리포트
```

---

## 5. 외부 의존성

### AI / LLM API

| 서비스 | 용도 | 어디서 사용 |
|--------|------|------------|
| **Anthropic Claude API** | 고품질 텍스트 생성, 전문 분석 | router, self_working, study |
| **OpenAI GPT-4o** | 코드 생성, 검토·비판 역할 | router (critic 프리셋), self_working |
| **LM Studio** (로컬) | 빠른 응답이 필요한 일반 질문, 분류 | router (hermes 프리셋), study |

### 데이터·서비스 API

| 서비스 | 용도 |
|--------|------|
| **Gmail OAuth** | 구독 이메일 수집 (daily_report) |
| **Yahoo Finance (yfinance)** | 시장 지수·주가 데이터 |
| **PubMed / Semantic Scholar** | 학술 논문 검색 (study-pipeline) |
| **Mem0 (원격 Chroma)** | 벡터 메모리 DB — Tailscale VPN 경유 |

### 주요 Python 라이브러리

| 라이브러리 | 역할 |
|-----------|------|
| `anthropic` | Claude API 클라이언트 |
| `openai` | GPT API 클라이언트 |
| `fastapi` | HTTP API 서버 (router) |
| `pydantic` | 데이터 구조 검증 |
| `beautifulsoup4` | 웹 페이지 파싱 |
| `playwright` | 헤드리스 브라우저 (크롤링 우회) |
| `yfinance` | 야후 파이낸스 데이터 |
| `pymupdf` | PDF → 텍스트 변환 |
| `watchdog` | 파일 변경 감지 |
| `scikit-learn` | TF-IDF 임베딩 (개념 유사도 계산) |
| `pyyaml` | YAML 설정 파일 읽기 |
| `typer` | CLI 명령어 인터페이스 |
| `google-auth-oauthlib` | Gmail OAuth 인증 |

---

## 6. 실행 방법

### daily_report_aggregator — 오늘의 금융 보고서 생성

```bash
# 1. 처음 1회만: Gmail OAuth 토큰 발급 (브라우저 창이 열림)
python collectors/gmail_reader.py --auth

# 2. 매일 실행: 모든 소스 수집 + 보고서 생성
cd daily_report_aggregator
python main.py
# → output/reports/2026-04-17/ 폴더에 Markdown 보고서 저장됨
```

### pbl-router-v4 — 라우터 서버 시작

```bash
# 서버 실행 (한 번 켜두면 다른 프로젝트들이 이 서버를 통해 AI와 통신)
cd pbl-router-v4
python router_server.py
# → http://localhost:8000 에서 대기

# 다른 터미널에서 테스트
python client.py "SN2 반응의 입체화학을 설명해줘"
```

### Self_Working_pipeline — AI 자동 개발 파이프라인

```bash
cd Self_Working_pipeline

# 1. 작업 기획 (요청 내용을 텍스트 파일로 작성 후)
python apps/cli/main.py plan --input request.txt

# 2. 기획서 검토 후 승인
python apps/cli/main.py approve --run-id <생성된_ID>

# 3. 코드 자동 생성 실행
python apps/cli/main.py run --run-id <생성된_ID>

# 4. 진행 상황 확인
python apps/cli/main.py status --run-id <생성된_ID>
```

### study-pipeline — 학습 자동화

```bash
cd study-pipeline

# 오늘의 공부 스케줄 생성
python scripts/hermes_agent.py

# 특정 과목 퀴즈 생성 (노트 경로 지정)
python scripts/generate.py --subject organic_chem

# 퀴즈 복습 시작
python scripts/review.py --subject organic_chem

# 노트 자동 감시 모드 (백그라운드 실행)
python scripts/watcher.py

# 시험 성적 기록
python scripts/record_exam.py --subject genomics_ai --score 85 --type exam

# 시험 오답 분석 리포트
python scripts/exam_postmortem.py --subject organic_chem
```

---

## 7. 설정 파일

### `.env` (각 프로젝트 루트에 위치)

직접 `.env` 파일을 만들고 아래 항목들을 채워야 합니다.  
**실제 키 값은 절대 Git에 올리면 안 됩니다.**

| 변수명 | 용도 | 필수 여부 |
|--------|------|----------|
| `ANTHROPIC_API_KEY` | Claude API 접근용 키 (anthropic.com에서 발급) | 필수 |
| `OPENAI_API_KEY` | GPT-4o 접근용 키 (platform.openai.com에서 발급) | 필수 |
| `LM_STUDIO_URL` | 로컬 LM Studio 서버 주소 (Tailscale VPN 경유) | 로컬 LLM 사용 시 필수 |
| `DISCORD_WEBHOOK_URL` | Self_Working_pipeline 완료 알림 전송용 | 선택 |
| `ROUTER_HOST` / `ROUTER_PORT` | 라우터 서버 바인딩 주소·포트 | 선택 (기본값 있음) |

### `study-pipeline/config.yaml`

YAML 형식의 230줄짜리 설정 파일. 주요 항목:

| 섹션 | 내용 |
|------|------|
| `scheduler` | SM-2(기본) 또는 FSRS 6.x 알고리즘 선택 |
| `interleaving` | 혼합 학습 모드 (off / soft / strict) |
| `energy_profile` | 시간대별 에너지 수준 → 어려운 개념 배치 기준 |
| `llm_routing` | 3단계 LLM 선택 기준 (로컬 Gemma → GPT → Claude) |
| `mem0` | 원격 Chroma 벡터 DB 주소 (Tailscale IP) |
| `subjects` | 3개 과목별 노트 경로, 템플릿, 교재 경로 |
| `paper_cache` | 논문 캐시 만료 기간 (기본 30일) |
| `pretest` | 사전 지식 체크 활성화 여부 |

### `pbl-router-v4/presets/*.preset.json`

각 AI 역할(프리셋)을 정의하는 JSON 파일. 담고 있는 내용:
- 사용할 모델 이름과 백엔드 종류 (local / anthropic / openai)
- 시스템 프롬프트 (AI의 역할 지침)
- temperature, max_tokens 등 생성 파라미터
- 응답 형식 (자유 텍스트 또는 JSON 스키마)

### `pbl-router-v4/profiles/*.profile.json`

모드별로 어떤 프리셋들을 활성화할지 정의. 예:
- `study.profile.json`: `hermes` + `lecture_parser` (빠르고 저렴한 조합)
- `work.profile.json`: `hermes` + `domain_expert` + `critic` (고품질 조합)

---

## 프로젝트 간 연결 관계

```
pbl-router-v4 (라우터 서버)
      ↑ HTTP 요청
      ├── study-pipeline/scripts/llm_router.py  (퀴즈 생성·분석 요청)
      └── Self_Working_pipeline/core/prompting.py (코드 생성 요청)

daily_report_aggregator  ←  독립 실행 (라우터 불필요)
```

---

*이 문서는 2026-04-17 기준 코드 상태를 반영합니다.*
