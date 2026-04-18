# Claude Desktop 통합 제안서

> Study Pipeline × Claude Desktop — 학습 중 모르는 개념을 즉시 질문하고 맥락 기반 설명을 받는 기능

**작성일:** 2026-04-15  
**상태:** Draft  
**예상 작업량:** 중~대 (핵심 MVP 3일, 전체 7일)

---

## 1. 목표

학습 중 모르는 개념이 나왔을 때 **Claude Desktop 앱에서 바로 질문**하면,
파이프라인이 축적한 학습 맥락(노트, 취약 개념, 교재 내용, 퀴즈 이력)을 활용하여
**개인화된 설명**을 받을 수 있도록 한다.

### 현재 문제
- Claude Desktop에 질문하면 일반적인 답변만 옴
- 내 노트 내용, 취약 개념, 교재 맥락을 모름
- 매번 배경 설명을 복붙해야 함

### 통합 후
- "carbocation 안정성이 왜 3차 > 2차인지?" 질문하면
  - 내 유기화학 노트에서 관련 내용 검색
  - 취약 개념(mastery 0.6) 기반으로 설명 깊이 조절
  - 교재 해당 페이지 내용 참조하여 답변
  - 관련 퀴즈에서 틀렸던 이력 언급

---

## 2. 기술 접근법: MCP Server

**핵심 아이디어:** Study Pipeline을 MCP(Model Context Protocol) 서버로 노출하여
Claude Desktop이 학습 데이터에 직접 접근하도록 한다.

```
┌─────────────────┐     MCP (stdio/SSE)     ┌──────────────────────┐
│  Claude Desktop  │ ◄──────────────────────► │  study-pipeline MCP  │
│  (질문/설명 요청) │                          │  server (Python)     │
└─────────────────┘                          └──────────┬───────────┘
                                                        │
                              ┌──────────────────────────┼──────────────┐
                              ▼                          ▼              ▼
                     Obsidian Vault              weak_concepts.json   교재 PDF
                     (노트 검색)                 (취약 개념 조회)      (텍스트 추출)
                              ▼                          ▼              ▼
                     learning_history.json        queue/ approved/    cache/
                     (퀴즈 이력)                 (퀴즈 데이터)       (논문/텍스트)
```

### 왜 MCP인가?

| 방안 | 장점 | 단점 |
|------|------|------|
| **A. MCP Server** | Claude Desktop 네이티브 지원, 양방향 도구 호출, 파일 접근 | MCP 서버 개발 필요 |
| B. Claude Projects | 간단한 파일 업로드 | 자동화 불가, 수동 갱신, 도구 호출 없음 |
| C. API 중계 | 자유도 높음 | 별도 UI 필요, Desktop 앱 활용 불가 |
| D. Obsidian 플러그인 | Obsidian 내 통합 | 별도 앱, Claude Desktop과 분리 |

**A안 (MCP Server)이 최적** — Claude Desktop이 MCP를 네이티브 지원하므로, 별도 UI 개발 없이 대화창에서 바로 학습 데이터를 검색·조회할 수 있다.

---

## 3. MCP Server 설계

### 3.1 제공 Tools (Claude가 호출)

```
study_search_notes(query, subject?)
  → 노트에서 키워드 검색, 관련 내용 반환

study_get_weak_concepts(subject?)
  → 취약 개념 목록 (mastery, priority, next_review)

study_get_textbook(subject, chapter?, pages?)
  → 교재 해당 부분 텍스트 추출

study_get_quiz_history(subject?, concept_tag?)
  → 퀴즈 풀이 이력 (정답률, 오답 메모)

study_explain_concept(concept, subject?)
  → 파이프라인 LLM 라우터로 심화 설명 생성
  → 취약도에 따라 설명 깊이 자동 조절

study_get_related_papers(topic)
  → 캐싱된 논문 요약 검색

study_create_quiz(concept_tags, difficulty?)
  → 특정 개념에 대한 즉석 퀴즈 생성 → queue/에 저장

study_record_result(concept_tag, result, memo?)
  → 대화 중 이해 여부를 기록 → weak_concepts 갱신
```

### 3.2 제공 Resources (정적 컨텍스트)

```
study://config          → 현재 과목 목록, 설정 요약
study://weekly-summary  → 이번 주 학습 통계
study://due-reviews     → 오늘 복습 예정 개념
```

### 3.3 제공 Prompts (대화 템플릿)

```
study-explain    → "이 개념을 내 수준에 맞게 설명해줘" (취약도 자동 반영)
study-quiz-me    → "이 주제로 퀴즈 내줘" (난이도 자동 조절)
study-review     → "오늘 복습할 내용 정리해줘" (SR 스케줄 기반)
```

---

## 4. 구현 계획

### Phase 1: MVP (3일)

**목표:** Claude Desktop에서 학습 노트 검색 + 취약 개념 조회가 되는 상태

```
scripts/
  mcp_server.py          ← MCP 서버 메인 (stdio transport)
  mcp_tools/
    __init__.py
    notes.py             ← study_search_notes
    concepts.py          ← study_get_weak_concepts
    textbook.py          ← study_get_textbook
```

**설치:**
```jsonc
// Claude Desktop config: %APPDATA%/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "study-pipeline": {
      "command": "python",
      "args": ["C:/Users/skyhu/Documents/AI_projects/study-pipeline/scripts/mcp_server.py"],
      "env": {
        "STUDY_PIPELINE_CONFIG": "C:/.../study-pipeline/scripts/config.yaml"
      }
    }
  }
}
```

**검증 시나리오:**
1. Claude Desktop 열기
2. "유기화학에서 내가 취약한 개념이 뭐야?" → `study_get_weak_concepts` 호출
3. "carbocation 안정성에 대해 교재에 뭐라고 나와?" → `study_get_textbook` 호출
4. "관련 노트 내용 검색해줘" → `study_search_notes` 호출

### Phase 2: 심화 설명 (2일)

- `study_explain_concept` — LLM 라우터 연동, 취약도 기반 설명 깊이 조절
- `study_get_quiz_history` — 오답 패턴 분석
- `study_get_related_papers` — 논문 캐시 검색

### Phase 3: 양방향 학습 (2일)

- `study_create_quiz` — 대화 중 즉석 퀴즈 생성
- `study_record_result` — 이해 여부 기록 → spaced repetition 반영
- Prompts 템플릿 (`study-explain`, `study-quiz-me`, `study-review`)
- 대시보드에 "Claude Desktop 연동 상태" 표시

---

## 5. 사용 시나리오

### 시나리오 A: 교재 읽다가 모르는 개념

```
나: "alkene의 Markovnikov rule이 뭐야? 교재 설명이 이해가 안 돼"

Claude: [study_get_weak_concepts 호출 → markovnikov: mastery 0.4]
        [study_get_textbook 호출 → Ch4 해당 페이지 추출]
        [study_search_notes 호출 → 관련 필기 검색]

        "너의 노트에 4월 9일 필기에서 Markovnikov rule을 다뤘는데,
         mastery가 0.4로 아직 취약한 개념이네.

         교재 Ch4 (p.168)에 따르면 ...
         너의 필기에서는 ...
         
         핵심은 ..."
```

### 시나리오 B: 복습 세션

```
나: "오늘 복습할 거 정리해줘"

Claude: [study://due-reviews 리소스 조회]
        [study_get_weak_concepts 호출]

        "오늘 복습 예정:
         🔴 carbocation_stability (mastery 0.6, 3일 간격)
         🟡 sn2_mechanism (mastery 0.7, 5일 간격)
         
         carbocation 안정성부터 시작할까?"

나: "응 설명해줘"

Claude: [study_explain_concept("carbocation_stability", "organic_chem")]
        [취약도 기반 심화 설명 생성]
```

### 시나리오 C: 즉석 퀴즈

```
나: "alkyne 관련해서 퀴즈 내봐"

Claude: [study_create_quiz(["terminal_alkyne", "alkyne_acidity"], "medium")]
        
        "Q1. Terminal alkyne이 약산성을 나타내는 이유를 
         sp 혼성화 관점에서 설명하시오."

나: "sp 혼성 탄소는 s 성격이 높아서 전자를 더 강하게 잡아서..."

Claude: [study_record_result("terminal_alkyne_acidity", "correct")]
        
        "정답! mastery 0.6 → 0.7로 업데이트됨.
         다음 복습은 5일 후."
```

---

## 6. 기술 스택

| 구성 | 선택 | 이유 |
|------|------|------|
| MCP SDK | `mcp` (Python) | 공식 SDK, stdio transport |
| Transport | stdio | Claude Desktop 기본, 설정 간단 |
| 의존성 | 기존 파이프라인 모듈 재사용 | llm_router, memory_manager, source_extractor 등 |
| 텍스트 검색 | 기존 Obsidian vault 파일 직접 검색 | 추가 DB 불필요 |
| 벡터 검색 | mem0 (Chroma) 기존 인프라 활용 | 의미 기반 노트 검색 |

### 의존성 추가

```
pip install mcp          # Anthropic MCP Python SDK
```

기존 패키지(pdfplumber, fitz, pyyaml 등)는 이미 설치되어 있으므로 추가 설치 최소.

---

## 7. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| MCP 서버 크래시 시 Claude Desktop 도구 사용 불가 | 중 | 에러 핸들링 + 로깅, 자동 재시작 |
| 교재 PDF 텍스트 추출 품질 | 중 | marker-pdf 캐시 활용, fallback 체인 |
| 대용량 노트 검색 지연 | 낮 | 캐싱 + 인덱스, 결과 truncation |
| Claude Desktop MCP 프로토콜 변경 | 낮 | 공식 SDK 사용으로 호환성 유지 |

---

## 8. 성공 지표

- [ ] Claude Desktop에서 `study_search_notes` 호출 → 3초 이내 응답
- [ ] 취약 개념 기반 설명 깊이 조절이 체감됨
- [ ] 즉석 퀴즈 → 결과 기록 → weak_concepts 반영 사이클 동작
- [ ] 기존 대시보드 Quiz Review와 데이터 일관성 유지

---

## 9. 다음 단계

1. **승인** → Phase 1 착수 (mcp_server.py 스캐폴딩)
2. Claude Desktop config에 MCP 서버 등록
3. `study_search_notes` + `study_get_weak_concepts` 구현 및 테스트
4. Phase 2~3 순차 진행
