# Study Pipeline Index

문서 상태: CURRENT INDEX  
최종 점검: 2026-04-28  
대상 폴더: `C:\Users\skyhu\Desktop\개인\Personal-sync-main\Personal-sync-main\study-pipeline`

이 문서는 현재 checkout에서 파이프라인을 다시 잡을 때 가장 먼저 보는 인덱스다. 현재 방향은 자동화 확장보다 수동 실행, GUI, Markdown 산출물, 로컬 JSON 학습 이력에 맞춘 단순한 학습 파이프라인이다.

---

## 1. 현재 상태 한 줄 요약

Study Pipeline은 노트/PDF/슬라이드를 합쳐 Markdown 정리본과 퀴즈를 만드는 로컬 중심 학습 파이프라인이다.

이번 정리에서 외부 router, Claude Desktop MCP, watcher/scheduler 자동 실행, PDF 출력, mem0 원격 의존성을 제거했다. 논문 보강은 설정에서 켜고 끌 수 있고, 퀴즈 생성과 Streamlit GUI는 유지한다.

---

## 2. 먼저 볼 파일

| 목적 | 파일 |
|---|---|
| 전체 구조 | `PIPELINE_OVERVIEW.md` |
| 코드 흐름 | `코드_로직_문서.md` |
| 사용자용 실행법 | `사용법_가이드.md` |
| 중앙 설정 | `scripts/config.yaml` |
| 의존성 | `scripts/requirements.txt`, `scripts/dashboard/requirements.txt` |
| 대시보드 | `scripts/dashboard/app.py` |
| 핵심 파이프라인 | `scripts/synthesize.py` |

---

## 3. 유지하는 기능

| 기능 | 상태 |
|---|---|
| 단일 노트 처리 | 유지 |
| 폴더 처리 | 유지 |
| 챕터 통합 | 유지 |
| PDF 입력 처리 | 유지 |
| 퀴즈 생성 | 유지 |
| 퀴즈 복습 CLI | 유지 |
| Hermes 일정 CLI | 유지 |
| Streamlit GUI | 유지 |
| Semantic Scholar/PubMed 논문 보강 | 선택 기능, 기본 OFF |
| Markdown 출력 | 유지, 기본 산출물 |
| 로컬 JSON 학습 이력 | 유지 |

---

## 4. 제거한 기능

| 제거 항목 | 이유 |
|---|---|
| 외부 router | 파이프라인 복잡도와 원격 의존성 감소 |
| Claude Desktop MCP | 더 이상 사용하지 않음 |
| watcher.py 실시간 감시 | 자동 실행 대신 명시적 수동 실행으로 정리 |
| scheduler.py / run_daily.bat | 예약 자동 실행 제거 |
| PDF 출력 | Markdown 산출물만 유지 |
| mem0ai 원격 기억 저장소 | 로컬 JSON으로 단순화 |

---

## 5. 핵심 실행 표면

| 작업 | 진입점 |
|---|---|
| 단일 노트 처리 | `python scripts/synthesize.py <note.md>` |
| 폴더 처리 | `python scripts/synthesize.py <folder>` |
| 챕터 통합 | `python scripts/synthesize.py --chapter <subject> <chapter>` |
| 챕터 전체 처리 | `python scripts/synthesize.py --chapter-all <subject>` |
| PDF만으로 처리 | `python scripts/synthesize.py --pdf-only <pdf1> [pdf2 ...] --subject <subject>` |
| 노트/PDF 소스 직접 지정 | `python scripts/synthesize.py --notes <note1> [note2 ...] --textbook <pdf> --slides <pdf> --subject <subject>` |
| 퀴즈 복습 CLI | `python scripts/review.py do` |
| Hermes 일정 CLI | `python scripts/hermes.py plan-day` / `plan-week` |
| 웹 대시보드 | `run_dashboard.bat` 또는 `streamlit run scripts/dashboard/app.py` |

---

## 6. 현재 설정 핵심값

| 항목 | 현재 방향 |
|---|---|
| `llm` | LM Studio, ChatGPT, Claude fallback |
| `papers.enabled` | `false` 기본값, 필요하면 GUI나 config에서 활성화 |
| `pubmed.enabled` | `false` 기본값, 필요하면 활성화 |
| `mem0.enabled` | `false` |
| `mem0.mode` | `local_json` |
| `output.formats` | `["md"]` |

주의: 출력/로그 경로는 `scripts/config.yaml`의 `pipeline_dir` 기준으로 결정된다. 현재 checkout과 실제 runtime 경로가 다를 수 있으므로 실행 전 `pipeline_dir`를 확인한다.

---

## 7. 주요 모듈 지도

| 영역 | 주요 파일 | 역할 |
|---|---|---|
| 오케스트레이션 | `scripts/synthesize.py` | 파이프라인 실행, Markdown 저장, 퀴즈 생성 |
| LLM 라우팅 | `scripts/llm_router.py`, `scripts/model_registry.py` | LM Studio / ChatGPT / Claude 선택 |
| 소스 추출 | `scripts/source_extractor.py`, `scripts/marker_reader.py`, `scripts/image_pipeline.py` | 노트, PDF, PPTX, 이미지 추출 |
| 논문 | `scripts/paper_fetcher.py`, `scripts/pubmed_client.py`, `scripts/paper_review.py` | 선택형 논문 보강 |
| 퀴즈 | `scripts/generate.py`, `scripts/textbook_quiz.py`, `scripts/quiz_store.py`, `scripts/quiz_cropper.py` | 퀴즈 생성, 승인/거절 저장 |
| 검증 | `scripts/verifier.py`, `scripts/templates/verifier_system.txt` | 합성 결과 점검 |
| 메모리/복습 | `scripts/memory_manager.py`, `scripts/mastery_tracker.py`, `scripts/migrate_to_fsrs.py` | 로컬 JSON 학습 이력, SM-2/FSRS |
| 일정 | `scripts/hermes.py`, `scripts/hermes_store.py`, `scripts/agents/hermes_agent.py` | 시험/에너지/약점 기반 계획 |
| 대시보드 | `scripts/dashboard/app.py`, `scripts/dashboard/pipeline_runner.py`, `scripts/dashboard/data_loader.py`, `scripts/dashboard/quiz_manager.py` | Streamlit UI |

---

## 8. 테스트 지도

| 테스트 파일 | 확인하는 축 |
|---|---|
| `tests/test_synthesize_smoke.py` | provenance 태그, smoke mode, PDF-only, 퀴즈 fallback |
| `tests/test_verifier_stage4.py` | verifier stage 4 판정 |
| `tests/test_verifier_llm_quick_scan_metadata.py` | verifier quick scan metadata |
| `tests/test_llm_router_fixes.py` | LLM fallback 관련 수정 |
| `tests/test_model_registry.py` | 모델 레지스트리 파싱/조회 fallback |
| `tests/test_memory_manager.py` | 로컬 학습 이력과 복습 fallback |
| `tests/test_fsrs_migration.py` | FSRS migration |
| `tests/test_energy_scheduling.py` | 에너지 기반 일정 |
| `tests/test_exam_postmortem.py` | 시험 회고 |
| `tests/test_quiz_store.py` | 퀴즈 파일 저장/이동 |
| `tests/test_quiz_cropper.py` | 교재 문제 cropper |
| `tests/test_quiz_generation_guardrails.py` | 퀴즈 생성 guardrail |
| `tests/test_pubmed_client_filters.py` | PubMed 필터 |
| `tests/test_pubmed_client_keywords.py` | PubMed 키워드 |
| `tests/test_lecture_chapter_mapping.py` | 챕터 라우팅 |
| `tests/test_pedagogy_exclude_patterns.py` | 교육 규칙 제외 패턴 |

---

## 9. 다음 작업 전 체크리스트

1. 현재 checkout에서 실행할지, `Documents\AI_projects\study-pipeline` runtime copy에서 실행할지 결정한다.
2. `scripts/config.yaml`의 `pipeline_dir`, `vault_path`, `notes_dir`가 원하는 위치인지 확인한다.
3. 논문 보강이 필요할 때만 `papers.enabled`와 `pubmed.enabled`를 켠다.
4. 실제 LLM 호출 전 LM Studio, OpenAI, Claude 키와 모델명을 확인한다.
5. 실행 후 `output/md`, `queue`, `cache/learning_history.json`, `logs/pipeline.log`를 확인한다.

---

## 10. 현재 결론

현재 상태는 `GO for manual MD workflow`다.

- 코드/테스트 관점: GO
- 문서/인덱스 관점: GO
- 실제 장시간 실행: LLM 서비스 상태 확인 후 GO
- 핵심 방향: 외부 자동화 표면을 줄이고, GUI와 CLI로 명시적으로 실행하는 Markdown 중심 파이프라인
