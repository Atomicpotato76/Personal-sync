# Study Pipeline — Phase 3 구현 계획서
> 다음 세션에 이 파일을 그대로 붙여넣으면 됩니다.

---

## 컨텍스트 (새 세션용 브리핑)

**프로젝트**: `C:\Users\skyhu\Documents\AI_projects\study-pipeline`
**핵심 파일**:
- `scripts/memory_manager.py` — 학습 메모리 관리 (SM-2 / FSRS 간격반복)
- `scripts/agents/hermes_agent.py` — 규칙 기반 일정 관리 에이전트
- `scripts/review.py` — 퀴즈 풀기 + 결과 기록
- `scripts/generate.py` — LLM 퀴즈 생성
- `scripts/synthesize.py` — 10단계 노트 합성 파이프라인
- `scripts/config.yaml` — 전체 설정 파일
- `tests/` — pytest 테스트 (현재 40개 전부 통과)

**완료된 것** (Phase 0~2):
- Phase 0: JSON 안전성 (corrupt 격리, RuntimeError), SM-2 interval 버그 수정, FSRS 6.x 통합
- Phase 1: 신뢰도 자기평가(1-5), 오답 분류(knowledge_gap/confusion/careless/misread), calibration 리포트
- Phase 2.1: 혼동 개념 인터리빙 (`confusable_with`, `interleaving_eligible`, hermes soft 모드)
- Phase 2.2: 사전 지식 체크 (pretest stub, wait_sec, `--pretest` CLI flag)
- Phase 2.3: 교차과목 시맨틱 링크 (`embed_note`, `find_similar_notes`, `_propagate_linked_mastery` 30%)
- Phase 2.4: 시험 가중치 (exam×2.0, mock_exam×1.5, `record_exam.py`, `--exam-deviation`)
- Phase 2.5: 문항 품질 평가 (`item_quality`, `retired`, `retire_low_quality.py`, 부정 예시 주입)

**새로 생긴 파일 목록**:
- `scripts/suggest_confusable_pairs.py`
- `scripts/approve_confusable.py`
- `scripts/approve_links.py`
- `scripts/record_exam.py`
- `scripts/retire_low_quality.py`
- `scripts/migrate_to_fsrs.py`
- `scripts/memory_manager_legacy.py`
- `tests/conftest.py`, `tests/test_memory_manager.py`, `tests/test_quiz_store.py`, `tests/test_fsrs_migration.py`

**ConceptEntry 현재 스키마** (`weak_concepts.json` 내 개념 하나):
```json
{
  "encounter_count": 5,
  "correct_count": 3,
  "last_encounter": "2026-04-17T10:00:00",
  "mastery": 0.6,
  "priority": "medium",
  "related_notes": [],
  "recent_mistakes": [],
  "sr_interval": 6,
  "sr_ease_factor": 2.5,
  "sr_next_review": "2026-04-23",
  "fsrs_card": null,
  "fsrs_next_review": null,
  "confusable_with": [],
  "interleaving_eligible": true,
  "cross_linked_concepts": [],
  "weighted_score": 3.0,
  "weighted_total": 5.0
}
```

**History event 현재 스키마** (`cache/learning_history.json`):
```json
{
  "timestamp": "2026-04-17T10:00:00",
  "subject": "organic_chem",
  "concepts": ["sn2"],
  "result": "correct",
  "source": "노트파일명",
  "confidence": 4,
  "error_category": null,
  "record_source": "quiz",
  "record_weight": 1.0
}
```

---

## Phase 3 구현 목표

### 3.1 역량 지도 (Competency Map)

**목적**: 과목별 개념들의 마스터리를 시각적으로 보여주는 ASCII/JSON 지도 생성

**구현 파일**: `scripts/competency_map.py` (신규)

**세부 작업**:

1. **`cmd_map(config, subject=None)`**: 과목별 개념을 마스터리 수준으로 묶어서 출력
   - 레벨 구분: `mastered(≥0.8)` / `learning(0.5~0.8)` / `struggling(<0.5)`
   - ASCII 트리 형태로 출력

2. **`cmd_export(config, output_path)`**: JSON 파일로 내보내기
   - Obsidian Canvas 또는 외부 시각화 도구용
   - 형식: `{ "nodes": [{"id", "label", "mastery", "priority", "subject"}], "edges": [{"source", "target", "type"}] }`
   - `cross_linked_concepts` 와 `confusable_with` 을 엣지로 표현

3. **`cmd_gap(config, subject)`**: 아직 `weak_concepts.json`에 없는데 노트에는 등장하는 개념 감지
   - `note_index.json` (단어 빈도 캐시) 에서 자주 나오는 단어 vs 등록된 concept_tags 비교
   - "아직 추적 안 되는 개념 후보" 목록 출력

**사용법 (목표)**:
```
python competency_map.py map [<과목>]
python competency_map.py export [--output competency.json]
python competency_map.py gap <과목>
```

---

### 3.2 논문 파이프라인 개선

**목적**: 논문 수집·요약 품질 향상 및 노트와의 연결 강화

**관련 파일**: `scripts/paper_fetcher.py`, `scripts/synthesize.py`, `scripts/pubmed_client.py`

**세부 작업**:

1. **`paper_fetcher.py` — 캐시 만료 + 재수집 로직**
   - 현재: 논문을 한 번 받으면 그냥 씀
   - 추가: `cache/papers/` 각 논문 JSON에 `cached_at` 필드 확인, 30일 지나면 재수집
   - `fetch_papers_for_note()` 에 `force_refresh: bool = False` 파라미터 추가

2. **`synthesize.py` step 5 — 논문 relevance 필터**
   - 현재: 최대 `max_papers_per_topic`개를 그냥 가져옴
   - 추가: `memory_manager.find_similar_notes()` 와 동일한 TF 유사도로 노트 내용과 논문 abstract 비교
   - 유사도 0.05 미만인 논문은 프롬프트에서 제외

3. **`scripts/paper_review.py` (신규)** — 논문 리뷰 CLI
   ```
   python paper_review.py list [<과목>]       # 캐시된 논문 목록
   python paper_review.py read <doi>          # abstract + 요점 출력
   python paper_review.py link <doi> <tag>    # 논문을 특정 concept_tag에 연결
   ```
   - `weak_concepts.json` 의 `related_notes` 필드에 DOI 추가

---

### 3.3 에너지 매칭 스케줄링

**목적**: 하루 중 시간대별 집중도에 맞춰 어려운 개념 vs 쉬운 복습을 자동 배치

**관련 파일**: `scripts/agents/hermes_agent.py`, `scripts/config.yaml`, `scripts/hermes_store.py`

**세부 작업**:

1. **`config.yaml` — energy_profile 추가**
   ```yaml
   energy_profile:
     "09:00": high    # 오전 = 집중력 높음
     "14:00": low     # 점심 후 = 집중력 낮음
     "20:00": medium  # 저녁 = 중간
   ```

2. **`hermes_store.py` — `get_daily_windows()` 에 energy 레벨 반환**
   - 현재: `{"start": "09:00", "duration_min": 60, "label": "오전 집중"}`
   - 추가: `"energy": "high"` 필드 포함

3. **`hermes_agent.py` — `_pick_task()` 에 energy 매칭 로직**
   - `energy=high` 슬롯 → priority=high + mastery<0.5 인 개념 우선 (어려운 것)
   - `energy=low` 슬롯 → priority=low + mastery≥0.8 인 개념 우선 (쉬운 복습)
   - `energy=medium` 슬롯 → 기존 score 기준 그대로
   - `_pick_task()` 에 `slot_energy: str = "medium"` 파라미터 추가
   - `_build_plan()` 에서 window의 energy 레벨을 읽어서 전달

4. **테스트**: `tests/test_energy_scheduling.py` 신규 작성
   - high 슬롯에는 어려운 개념이 먼저 배치되는지 검증
   - low 슬롯에는 쉬운 복습이 먼저 배치되는지 검증

---

### 3.4 시험 사후 분석 (Exam Postmortem)

**목적**: 시험 끝난 후 "왜 틀렸는지" 체계적으로 정리하고 다음 공부 계획에 반영

**관련 파일**: `scripts/record_exam.py`, `scripts/review.py`, `scripts/memory_manager.py`

**세부 작업**:

1. **`scripts/exam_postmortem.py` (신규)**
   ```
   python exam_postmortem.py start <과목> [<시험명>]   # 사후 분석 세션 시작
   python exam_postmortem.py report [<과목>]           # 분석 결과 리포트
   ```
   - `start`: 틀린 문제를 하나씩 입력받음 (개념 태그, 오답 원인, 메모)
   - 내부적으로 `record_exam.py` 의 `cmd_add()` 를 호출 (`source=exam`)
   - 입력 완료 후 "이번 시험 약점 TOP 3" 즉시 출력

2. **`record_exam.py` — `postmortem` 서브커맨드 추가**
   ```
   python record_exam.py postmortem <과목> [--exam-name "중간고사"]
   ```
   - 대화형으로 문항 번호, 개념, 오답 원인을 입력
   - 끝나면 `hermes_agent.refresh_from_event("exam_postmortem")` 호출 → 다음 주 계획 자동 갱신

3. **`memory_manager.py` — `get_postmortem_summary()` 추가**
   ```python
   def get_postmortem_summary(self, subject: str, exam_name: str | None = None) -> dict:
   ```
   - 반환: `{"top_weak": [...], "error_distribution": {...}, "recommended_focus": [...]}`
   - `history.events` 에서 `record_source == "exam"` 인 것만 필터
   - `error_category` 분포 계산
   - 가장 자주 틀린 개념 TOP 5

4. **`review.py report` — `--postmortem` 플래그 추가**
   ```
   python review.py report --postmortem [<과목>]
   ```
   - `get_postmortem_summary()` 결과를 보기 좋게 출력
   - 섹션: 오답 분포 / 취약 개념 순위 / 다음 주 추천 집중 개념

5. **테스트**: `tests/test_exam_postmortem.py` 신규 작성
   - `get_postmortem_summary()` 가 올바른 집계 반환하는지 검증
   - exam 이벤트만 필터링되는지 검증

---

## 구현 순서 (권장)

```
3.3 → 3.4 → 3.1 → 3.2
```
이유:
- **3.3** 은 hermes_agent.py 수정이 핵심 → 테스트 쓰기 쉬움
- **3.4** 는 record_exam.py/memory_manager.py 확장 → 기존 구조 잘 앎
- **3.1** 은 새 파일(competency_map.py) 추가 → 다른 파일 건드림 적음
- **3.2** 는 논문 파이프라인이 가장 외부 의존성 많음 → 마지막에

---

## 작업 시작 전 체크리스트

```bash
# 현재 테스트 상태 확인
cd C:\Users\skyhu\Documents\AI_projects\study-pipeline
python -m pytest tests/ -q
# → 40 passed 확인

# 주요 파일 읽기 (컨텍스트 확보)
# 1. scripts/memory_manager.py (전체)
# 2. scripts/agents/hermes_agent.py (전체)
# 3. scripts/hermes_store.py (energy profile 추가 위치 파악)
# 4. scripts/record_exam.py (3.4 확장 기준점)
```

---

## 완료 기준

각 Phase가 끝나면:
- [ ] `python -m pytest tests/ -q` → 전부 통과
- [ ] 새로 추가한 기능은 테스트 최소 3개 이상
- [ ] `config.yaml` 에 새 설정 키 추가 시 기본값 안전하게 설정 (기존 동작 변경 없음)
- [ ] 한국어 사용자 대상 CLI이므로 모든 출력 메시지 한국어 유지
