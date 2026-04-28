# Study Pipeline Index

문서 상태: CURRENT INDEX  
최종 점검: 2026-04-28  
대상 폴더: `C:\Users\skyhu\Desktop\개인\Personal-sync-main\Personal-sync-main\study-pipeline`

이 문서는 현재 checkout에서 파이프라인을 다시 잡을 때 가장 먼저 보는 인덱스다. 세부 설명은 기존 문서로 넘기고, 여기에는 현재 상태, 진입점, 검증 결과, 리스크만 모은다.

---

## 1. 현재 상태 한 줄 요약

Study Pipeline v3는 정적 코드 검증 기준으로 정상이다. `compileall`과 전체 테스트가 통과했고, `--pdf-only`, 소스 직접 지정, 챕터 통합, 대시보드, MCP, Hermes 일정 기능이 코드상 연결되어 있다.

다만 실제 런타임 출력/로그 경로는 현재 checkout이 아니라 `C:\Users\skyhu\Documents\AI_projects\study-pipeline`로 설정되어 있으며, 2026-04-28 점검 시 LM Studio, 외부 router, Chroma 같은 원격 서비스는 타임아웃으로 연결 확인에 실패했다.

---

## 2. 먼저 볼 파일

| 목적 | 파일 |
|---|---|
| 전체 구조와 비전 | `PIPELINE_OVERVIEW.md` |
| 코드 흐름과 모듈 계약 | `코드_로직_문서.md` |
| 사용자용 실행법 | `사용법_가이드.md` |
| 이전 구현 완료 내역 | `완료보고서.md` |
| 다음 단계/확장 계획 | `PHASE3_PLAN.md` |
| 제안서/개선 방향 | `1차_수정_제안서.md`, `proposals/claude_desktop_integration.md` |
| 중앙 설정 | `scripts/config.yaml` |
| 의존성 | `scripts/requirements.txt`, `scripts/dashboard/requirements.txt` |

---

## 3. 핵심 실행 표면

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
| Claude Desktop MCP | `python scripts/mcp_server.py` |

---

## 4. 현재 코드 상태

### 정상 확인

- `scripts/synthesize.py`에 `process_pdf_only(...)`와 `--pdf-only` CLI 분기가 있다.
- `scripts/dashboard/app.py`에 `PDF Only` 실행 모드가 있다.
- `scripts/dashboard/pipeline_runner.py`에 `start_pdf_only(...)`가 있다.
- `tests/test_synthesize_smoke.py`가 PDF-only 실행과 PDF 텍스트 기반 퀴즈 fallback을 검증한다.
- verifier는 `required_topics`가 비어 있을 때 과도하게 실패하지 않도록 테스트 범위에 포함되어 있다.
- 현재 `study-pipeline`은 상위 `Personal-sync-main` git repo 안의 하위 폴더다. 초기 점검 때 하위 폴더 단독 기준으로는 `.git`이 보이지 않았지만, 현재 원격은 `Atomicpotato76/Personal-sync`로 확인된다.

### 검증 결과

2026-04-28 현재 checkout에서 실행:

```powershell
python -m compileall scripts tests
python -m pytest -q
```

결과:

- `compileall`: PASS
- `pytest`: `118 passed in 4.20s`

---

## 5. 런타임 경로 상태

`scripts/config.yaml` 기준:

| 항목 | 현재 설정 |
|---|---|
| Vault | `C:/Users/skyhu/Documents/Obsidian Vault` |
| notes_dir | `3학년 1학기/중간고사` |
| pipeline_dir | `C:/Users/skyhu/Documents/AI_projects/study-pipeline` |
| scripts_dir | `C:/Users/skyhu/Documents/AI_projects/study-pipeline/scripts` |

주의:

- 현재 checkout은 `Desktop\개인\Personal-sync-main\Personal-sync-main\study-pipeline`이다.
- 하지만 출력, 로그, queue, cache는 설정상 `Documents\AI_projects\study-pipeline` 아래로 간다.
- `STUDY_PIPELINE_DIR`, `STUDY_SCRIPTS_DIR`, `STUDY_VAULT_PATH`, `STUDY_CACHE_DIR` 환경변수로 경로 override가 가능하다.

2026-04-28 확인한 실제 경로:

| 경로 | 상태 |
|---|---|
| `C:\Users\skyhu\Documents\AI_projects\study-pipeline` | 존재 |
| `C:\Users\skyhu\Documents\AI_projects\study-pipeline\output\md` | 존재 |
| `C:\Users\skyhu\Documents\AI_projects\study-pipeline\queue` | 존재 |
| `C:\Users\skyhu\Documents\AI_projects\study-pipeline\logs` | 존재 |
| `C:\Users\skyhu\Documents\Obsidian Vault` | 존재 |

최근 `pipeline.log`의 마지막 성공 기록은 2026-04-22 08:19경 PDF-only mycology Chapter 4 완료이며, verifier는 `PASS (100/100)`였다.

---

## 6. 외부 서비스 상태

2026-04-28 현재 이 머신에서 단기 연결 확인:

| 서비스 | 설정/대상 | 결과 |
|---|---|---|
| LM Studio | `http://100.78.18.95:1234/v1/models` | timeout |
| Router | `http://100.67.163.118:8000/health` | timeout |
| Chroma/mem0 | `100.78.18.95:8001` | timeout |

해석:

- 코드와 테스트는 살아 있다.
- 장시간 실제 파이프라인 실행은 원격 LLM/router/vector store 상태에 영향을 받는다.
- `mem0` 원격 Chroma 실패는 과거 로그에서도 local JSON fallback으로 degrade 처리되었고, 그 자체만으로 전체 실패는 아니었다.
- LM Studio와 router는 현재 연결 확인이 안 되었으므로 실제 실행 전 서버 상태를 먼저 확인해야 한다.

---

## 7. 모델/API 확인 메모

프로젝트 규칙상 모델명은 최신성 확인이 필요하다. 2026-04-28 공식 문서 검색 기준:

- OpenAI 공식 모델 문서에는 `GPT-5.2`, `GPT-5.1`, `GPT-5`, `GPT-5 mini/nano` 등이 표시되며, 현재 `scripts/config.yaml`의 `gpt-5.5`는 공식 문서 검색 결과에서 직접 확인되지 않았다. 실제 사용 가능 여부는 대상 계정의 `/v1/models` 응답으로 확인해야 한다.
- Anthropic 공식 모델 문서에는 API 모델명으로 `claude-sonnet-4-20250514`, `claude-opus-4-1-20250805` 등이 표시된다. 현재 `scripts/config.yaml`의 `claude-sonnet-4-6`은 공식 모델 표에서 직접 확인되지 않았으므로 API fallback 전 확인이 필요하다.
- Anthropic `anthropic-version: 2023-06-01` 헤더는 공식 versioning 문서의 예시와 일치한다.
- 런타임 로그에서는 OpenAI 모델 조회 결과에 `gpt-5.4`, `gpt-5.2`, `gpt-5.1` family가 잡혔고, 실제 호출은 `gpt-5.4-2026-03-05`로 기록된 적이 있다. 이 로그는 2026-04-22 당시 환경 기준이며, 현재 계정 상태는 재확인이 필요하다.

공식 확인 링크:

- OpenAI models: https://platform.openai.com/docs/models
- OpenAI model API reference: https://platform.openai.com/docs/api-reference/models
- Anthropic models: https://docs.anthropic.com/en/docs/about-claude/models/all-models
- Anthropic versioning: https://docs.anthropic.com/en/api/versioning

---

## 8. 주요 모듈 지도

| 영역 | 주요 파일 | 역할 |
|---|---|---|
| 오케스트레이션 | `scripts/synthesize.py` | 10단계 파이프라인, PDF-only, 챕터 통합, 직접 소스 처리 |
| 파일 감시 | `scripts/watcher.py` | Obsidian 변경 감지 후 처리 |
| LLM 라우팅 | `scripts/llm_router.py`, `scripts/model_registry.py` | LM Studio / OpenAI / Claude / 외부 router 선택 |
| 소스 추출 | `scripts/source_extractor.py`, `scripts/marker_reader.py`, `scripts/image_pipeline.py` | 노트, PDF, PPTX, 이미지 추출 |
| 논문 | `scripts/paper_fetcher.py`, `scripts/pubmed_client.py`, `scripts/paper_review.py` | Semantic Scholar / PubMed 보강 |
| 퀴즈 | `scripts/generate.py`, `scripts/textbook_quiz.py`, `scripts/quiz_store.py`, `scripts/quiz_cropper.py` | 퀴즈 생성, 교재 문제, 승인/거절 저장 |
| 검증 | `scripts/verifier.py`, `scripts/templates/verifier_system.txt` | Stage 4 검증 |
| 메모리/복습 | `scripts/memory_manager.py`, `scripts/mastery_tracker.py`, `scripts/migrate_to_fsrs.py` | SM-2/FSRS, weak concepts, mem0 fallback |
| 일정 | `scripts/hermes.py`, `scripts/hermes_store.py`, `scripts/agents/hermes_agent.py` | 시험/에너지/약점 기반 계획 |
| MCP | `scripts/mcp_server.py`, `scripts/mcp_tools/` | Claude Desktop 도구 표면 |
| 대시보드 | `scripts/dashboard/app.py`, `scripts/dashboard/pipeline_runner.py`, `scripts/dashboard/data_loader.py`, `scripts/dashboard/quiz_manager.py` | Streamlit UI |

---

## 9. 테스트 지도

| 테스트 파일 | 확인하는 축 |
|---|---|
| `tests/test_synthesize_smoke.py` | provenance 태그, smoke mode, PDF-only, 퀴즈 fallback |
| `tests/test_verifier_stage4.py` | verifier stage 4 판정 |
| `tests/test_verifier_llm_quick_scan_metadata.py` | verifier quick scan metadata |
| `tests/test_llm_router_fixes.py` | LLM routing 관련 수정 |
| `tests/test_model_registry.py` | 모델 레지스트리 파싱/조회 fallback |
| `tests/test_memory_manager.py` | 메모리/복습 fallback |
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

## 10. 다음 작업 전 체크리스트

1. 실제 실행 전 LM Studio `/v1/models` 응답을 확인한다.
2. `scripts/config.yaml`의 `llm.chatgpt.model`, `llm.claude.model`, `mem0.llm.model`이 현재 서버/계정에서 유효한지 확인한다.
3. 현재 checkout에서 실행할지, `Documents\AI_projects\study-pipeline` runtime copy에서 실행할지 결정한다.
4. 현재 checkout 기준으로 실행하려면 `STUDY_PIPELINE_DIR`와 `STUDY_SCRIPTS_DIR`를 명시하거나 `config.yaml` 경로를 조정한다.
5. 긴 PDF-only 실행은 콘솔 완료만 기다리지 말고 `logs/pipeline.log`, `output/md`, `queue`를 함께 확인한다.
6. `rg.exe`가 Access denied일 수 있으므로 Windows에서는 PowerShell `Get-ChildItem` + `Select-String` fallback을 사용한다.

---

## 11. 현재 결론

현재 상태는 `GO with service caveat`다.

- 코드/테스트 관점: GO
- 문서/인덱스 관점: GO
- 실제 장시간 파이프라인 실행: 원격 서비스 상태 확인 후 GO
- 즉시 주의할 점: 현재 checkout과 runtime 경로가 다르므로, 수정한 파일이 실제 실행 경로에 반영되는지 확인해야 한다.
