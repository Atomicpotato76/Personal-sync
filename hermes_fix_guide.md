# Hermes Pipeline 수정 가이드

이 문서는 Hermes 멀티에이전트 파이프라인의 로직 이슈 수정 + 자동 조사 파이프라인 변환을 위한 가이드입니다.
Codex 또는 AI 코딩 에이전트에게 전달하여 수정을 지시하세요.

---

## Part 1: 로직 이슈 수정 (4건)

### Issue 1: retry count 이중 관리

**파일:** `services/orchestrator/service.py`

**문제:**
`_execute_workstream_until_approved` (360~419줄)에서 review 실패 시 retry_count를 올리고,
`_execute_until_gate` (324~358줄)에서 test 실패 시에도 retry_count를 올린다.
하나의 workstream이 review retry + test retry를 모두 겪으면 max_retries에 예상보다 빨리 도달한다.

**수정 방법:**
retry_count를 용도별로 분리하거나, 현재 방식을 유지하되 max_retries 체크 시 어떤 종류의 retry인지 구분한다.

**구체적 수정 — 방법 A (권장: 단순한 방법):**

`_execute_until_gate` 메서드의 test failure retry 부분(약 331~346줄)에서,
retry_count를 올릴 때 기존 review retry와 합산하지 않도록 별도 카운터를 사용한다:

```python
# 변경 전 (약 333줄):
retry_count = item["retry_count"] + 1
if retry_count > self.max_retries_per_workstream:

# 변경 후:
# test failure로 인한 retry는 review retry와 별도로 카운트
# latest_feedback에 "test_failure" 마커를 추가하여 구분
test_retry_count = sum(
    1 for fb in item["latest_feedback"] if fb.startswith("[test-failure]")
)
if test_retry_count >= self.max_retries_per_workstream:
    # ... 기존 실패 처리 로직
```

그리고 test failure feedback을 저장할 때 prefix를 붙인다:

```python
# 변경 전 (약 345줄):
latest_feedback=[report.stderr or report.stdout or "Fix failing tests."],

# 변경 후:
latest_feedback=[f"[test-failure] {report.stderr or report.stdout or 'Fix failing tests.'}"],
```

**구체적 수정 — 방법 B (깔끔한 방법):**

WorkstreamEntity 모델(`services/memory/models.py`)에 `test_retry_count` 필드를 추가하고,
MemoryService의 `update_workstream`에도 해당 파라미터를 추가한다.
orchestrator에서 review retry는 기존 `retry_count`, test retry는 `test_retry_count`로 분리 관리한다.

---

### Issue 2: stale read 가능성

**파일:** `services/orchestrator/service.py`
**위치:** `_execute_workstream_until_approved` 메서드, 약 362줄

**문제:**
```python
while True:
    ready = next(item for item in self.memory.list_workstreams(run_id) if item["workstream_id"] == workstream_id)
    # ... executor, reviewer 실행 ...
    retry_count = ready["retry_count"] + 1  # ← ready는 루프 시작 시점의 스냅샷
```

`ready`는 루프 시작 시점에서 읽은 값인데, executor와 reviewer가 내부적으로 workstream을 업데이트한 후에도
여전히 오래된 `ready` 딕셔너리의 `retry_count`를 사용한다.
현재는 single-threaded라 문제 없지만, parallel workstream 실행 시 race condition 발생 가능.

**수정:**
retry_count 계산 직전에 workstream을 다시 읽는다:

```python
# 변경 전 (약 391~393줄):
retry_count = ready["retry_count"] + 1
if retry_count > self.max_retries_per_workstream:

# 변경 후:
# review 결과 처리 후, 최신 workstream 상태를 다시 읽어서 retry_count를 정확히 계산
fresh_ws = next(
    item for item in self.memory.list_workstreams(run_id)
    if item["workstream_id"] == workstream_id
)
retry_count = fresh_ws["retry_count"] + 1
if retry_count > self.max_retries_per_workstream:
```

---

### Issue 3: approval_stage None fallback

**파일:** `services/orchestrator/service.py`
**위치:** `supervise` 메서드, 약 187~195줄

**문제:**
```python
if session.cycles_completed >= session.max_cycles:
    trace = self._build_policy_trace(
        run_id,
        stage=approval_stage or ApprovalStage.checkpoint,  # ← None일 때 checkpoint로 fallback
```

`approval_stage`가 None이면 실제 상태와 무관하게 `checkpoint`로 기록된다.
디버깅 시 trace에 잘못된 stage가 남아 혼란을 줄 수 있다.

**수정:**
현재 run의 실제 stage를 기반으로 적절한 ApprovalStage를 추론한다:

```python
# 변경 전:
stage=approval_stage or ApprovalStage.checkpoint,

# 변경 후:
stage=approval_stage or self._infer_approval_stage_from_run(run),
```

그리고 아래에 헬퍼 메서드를 추가한다:

```python
@staticmethod
def _infer_approval_stage_from_run(run: RunRecord) -> ApprovalStage:
    """Run의 현재 stage를 기반으로 가장 적절한 ApprovalStage를 추론한다."""
    if run.stage == RunStage.planning:
        return ApprovalStage.plan
    if run.stage == RunStage.testing:
        return ApprovalStage.merge
    return ApprovalStage.checkpoint
```

---

### Issue 4: approve 비대칭 (문서화)

**파일:** `services/orchestrator/service.py`
**위치:** `approve` 메서드, 약 62~100줄

**문제:**
- plan approve → stage를 `plan_approved`로 전이 (stage 변경 O)
- checkpoint approve → stage 변경 없이 status만 `pending`으로 변경 (stage 변경 X)
- merge approve → stage를 `merge_approved`로 전이 (stage 변경 O)

이는 의도된 설계(checkpoint는 같은 executing stage에서 계속 진행)이지만, 코드만 보면 헷갈린다.

**수정:** 동작은 그대로 두되, 명시적 주석을 추가한다:

```python
# checkpoint approve 부분 (약 75줄):
if stage == ApprovalStage.checkpoint:
    # NOTE: checkpoint approval은 stage를 전이하지 않는다.
    # executing/reviewing stage 내에서 다음 workstream으로 계속 진행하기 위해
    # status만 pending으로 되돌린다. plan/merge approve와 달리
    # 새로운 RunStage로의 전이가 필요하지 않다.
    if run.stage not in {RunStage.executing, RunStage.reviewing} or run.status not in {
```

---

## Part 2: 설정 수정

### 하드코딩 경로 제거

**파일:** `core/settings.py`
**위치:** 10줄

```python
# 변경 전:
default_guidance_prompt_path: Path | None = Path(r"C:\Users\skyhu\Downloads\vibe-coding-prompts.md")

# 변경 후:
default_guidance_prompt_path: Path | None = None
```

이 값은 `.env` 파일이나 환경변수 `DEFAULT_GUIDANCE_PROMPT_PATH`로 주입하도록 한다.
pydantic-settings가 자동으로 환경변수를 읽으므로 추가 코드 변경 없이 동작한다.

---

## Part 3: 자동 조사 파이프라인 변환

Hermes의 orchestrator, state machine, supervisor, memory, notifier는 그대로 재사용한다.
변경이 필요한 것은 executor의 prompt, tester의 로직, 그리고 관련 contracts 모델이다.

### 3-1. Executor system prompt 변경

**파일:** `services/executor/service.py`

executor의 system prompt과 user prompt을 조사용으로 변경한다:

```python
class ExecutorService:
    def __init__(self, adapter: JsonModelAdapter, *, guidance_prompt: str = "", mode: str = "code") -> None:
        self.adapter = adapter
        self.guidance_prompt = guidance_prompt
        self.mode = mode

    def execute(
        self,
        *,
        assignment: TaskAssignment,
        plan_bundle: PlanBundle,
        workspace_snapshot: str,
        review_feedback: list[str],
    ) -> ExecutionResult:
        feedback_text = "\n".join(f"- {item}" for item in review_feedback) or "- none"

        if self.mode == "research":
            system_prompt = compose_system_prompt(
                (
                    "You are a research agent in a multi-agent investigation pipeline. "
                    "Your job is to research the assigned topic thoroughly, cite sources, "
                    "and produce well-structured investigation results. "
                    "Return your findings as structured files (markdown reports)."
                ),
                self.guidance_prompt,
                section_name="research methodology, source verification, and output formatting",
            )
            user_prompt = (
                "Research the following topic and produce investigation results.\n"
                "Rules:\n"
                "- cite all claims with source URLs or references\n"
                "- distinguish facts from speculation\n"
                "- flag any conflicting information found across sources\n"
                "- produce one or more markdown files with your findings\n"
                "- keep scope focused on the assigned workstream only\n\n"
                f"Task assignment:\n{assignment.model_dump_json(indent=2)}\n\n"
                f"Plan bundle:\n{plan_bundle.model_dump_json(indent=2)}\n\n"
                f"Current workspace snapshot:\n{workspace_snapshot or '[empty workspace]'}\n\n"
                f"Review feedback to address:\n{feedback_text}\n\n"
                "Return JSON only."
            )
        else:
            # 기존 코드 생성 모드 (원래 system_prompt과 user_prompt)
            system_prompt = compose_system_prompt(
                (
                    "You are Codex acting as the implementation agent in a controlled delivery pipeline. "
                    "Write only the files needed for the assigned workstream and keep changes scoped."
                ),
                self.guidance_prompt,
                section_name="implementation, repository expectations, testing, reversibility, and workflow rules",
            )
            user_prompt = (
                "Create or update files for this workstream.\n"
                "Rules:\n"
                "- modify only files relevant to the workstream layer\n"
                "- include tests when the workstream implies behavior\n"
                "- keep dependencies minimal and use Python standard library when possible\n"
                "- honor any user additions recorded in plan_bundle.change_log\n"
                "- return relative file paths only\n\n"
                f"Task assignment:\n{assignment.model_dump_json(indent=2)}\n\n"
                f"Plan bundle:\n{plan_bundle.model_dump_json(indent=2)}\n\n"
                f"Current workspace snapshot:\n{workspace_snapshot or '[empty workspace]'}\n\n"
                f"Review feedback to address:\n{feedback_text}\n\n"
                "Return JSON only."
            )

        result = self.adapter.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=ExecutionEnvelope,
        )
        assert isinstance(result, ExecutionEnvelope)
        return result.result
```

### 3-2. Reviewer system prompt 변경

**파일:** `services/reviewer/service.py`

reviewer도 mode에 따라 prompt을 분기한다:

```python
class ReviewerService:
    def __init__(self, adapter: JsonModelAdapter, *, guidance_prompt: str = "", mode: str = "code") -> None:
        self.adapter = adapter
        self.guidance_prompt = guidance_prompt
        self.mode = mode

    def review(self, *, execution_result: ExecutionResult, plan_bundle: PlanBundle) -> ReviewReport:
        if self.mode == "research":
            system_prompt = compose_system_prompt(
                (
                    "You are a fact-checker and quality reviewer in a multi-agent investigation pipeline. "
                    "Evaluate research findings for accuracy, source quality, completeness, "
                    "logical consistency, and alignment with the investigation plan."
                ),
                self.guidance_prompt,
                section_name="fact-checking, source verification, and research quality standards",
            )
            user_prompt = (
                "Review the investigation results against the plan bundle.\n"
                "Check for:\n"
                "- unsupported claims (claims without sources)\n"
                "- conflicting information not flagged by the researcher\n"
                "- missing coverage of required subtopics\n"
                "- logical gaps or non-sequiturs\n"
                "- source quality (prefer academic, official, and authoritative sources)\n"
                "Approve only when the research is complete, well-sourced, and aligned with the plan.\n"
                "Return JSON only.\n\n"
                f"Plan bundle:\n{plan_bundle.model_dump_json(indent=2)}\n\n"
                f"Research results:\n{execution_result.model_dump_json(indent=2)}"
            )
        else:
            # 기존 코드 리뷰 모드 (원래 prompt)
            system_prompt = compose_system_prompt(
                (
                    "You are Claude Code acting as a reviewer. Evaluate generated files for correctness, "
                    "scope control, maintainability, and alignment with the contract."
                ),
                self.guidance_prompt,
                section_name="review, testing discipline, repository expectations, and safety rules",
            )
            user_prompt = (
                "Review the implementation against the plan bundle.\n"
                "Approve only when the workstream is complete, scoped correctly, "
                "and still follows any user additions in plan_bundle.change_log.\n"
                "Return JSON only.\n\n"
                f"Plan bundle:\n{plan_bundle.model_dump_json(indent=2)}\n\n"
                f"Execution result:\n{execution_result.model_dump_json(indent=2)}"
            )

        result = self.adapter.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=ReviewEnvelope,
        )
        assert isinstance(result, ReviewEnvelope)
        return result.report
```

### 3-3. Tester를 조사 검증 로직으로 교체

**파일:** `services/testing/service.py`

조사 파이프라인에서는 pytest 대신 교차검증 로직을 실행한다:

```python
class TestRunnerService:
    def __init__(self, *, mode: str = "code") -> None:
        self.mode = mode

    def run(self, workspace_path: Path) -> TestReport:
        if self.mode == "research":
            return self._run_research_validation(workspace_path)
        return self._run_pytest(workspace_path)

    def _run_research_validation(self, workspace_path: Path) -> TestReport:
        """조사 결과물의 기본 품질 검증을 수행한다."""
        results: list[TestResult] = []

        # 1. 결과 파일 존재 여부 확인
        md_files = list(workspace_path.rglob("*.md"))
        if not md_files:
            results.append(TestResult(
                name="output_files_exist",
                passed=False,
                details="No markdown output files found in workspace."
            ))
            return TestReport(
                passed=False,
                command="research_validation",
                results=results,
                stderr="No output files found.",
            )
        results.append(TestResult(
            name="output_files_exist",
            passed=True,
            details=f"Found {len(md_files)} markdown file(s)."
        ))

        # 2. 빈 파일 체크
        empty_files = [f for f in md_files if f.stat().st_size < 100]
        has_content = len(empty_files) == 0
        results.append(TestResult(
            name="files_have_content",
            passed=has_content,
            details=f"{len(empty_files)} file(s) are nearly empty." if not has_content else "All files have content."
        ))

        # 3. 출처/참조 포함 여부 (간단한 heuristic)
        files_with_refs = 0
        for md_file in md_files:
            content = md_file.read_text(encoding="utf-8", errors="ignore").lower()
            if any(marker in content for marker in ["http", "source:", "reference", "doi:", "출처", "참고"]):
                files_with_refs += 1
        has_refs = files_with_refs > 0
        results.append(TestResult(
            name="sources_cited",
            passed=has_refs,
            details=f"{files_with_refs}/{len(md_files)} file(s) contain source references."
        ))

        # 4. 최소 분량 체크
        total_chars = sum(f.stat().st_size for f in md_files)
        min_chars = 500
        meets_length = total_chars >= min_chars
        results.append(TestResult(
            name="minimum_length",
            passed=meets_length,
            details=f"Total output: {total_chars} chars (minimum: {min_chars})."
        ))

        passed = all(r.passed for r in results)
        return TestReport(
            passed=passed,
            command="research_validation",
            results=results,
            stdout=f"Validated {len(md_files)} file(s), {total_chars} total chars.",
            stderr="" if passed else "Some validation checks failed.",
        )

    def _run_pytest(self, workspace_path: Path) -> TestReport:
        """기존 pytest 실행 로직 (원래 코드 그대로)"""
        tests_dir = workspace_path / "tests"
        if not tests_dir.exists():
            return TestReport(
                passed=False,
                command="pytest -q",
                results=[TestResult(name="tests_present", passed=False, details="No tests directory found.")],
                stderr="No tests directory found.",
            )
        command = [sys.executable, "-m", "pytest", "-q"]
        completed = subprocess.run(
            command,
            cwd=workspace_path,
            capture_output=True,
            text=True,
            check=False,
        )
        return TestReport(
            passed=completed.returncode == 0,
            command=" ".join(command),
            results=[
                TestResult(
                    name="pytest",
                    passed=completed.returncode == 0,
                    details=f"exit_code={completed.returncode}",
                )
            ],
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
```

### 3-4. Planner system prompt 변경

**파일:** `services/planner/service.py`
**위치:** `create_plan` 메서드, 약 129줄

planner도 mode를 받아서 조사용 plan을 생성하도록 한다:

```python
class PlannerService:
    def __init__(self, adapter: JsonModelAdapter, *, guidance_prompt: str = "", 
                 request_digest_chars: int = 4000, mode: str = "code") -> None:
        self.adapter = adapter
        self.guidance_prompt = guidance_prompt
        self.request_digest_chars = request_digest_chars
        self.mode = mode

    def create_plan(self, user_request: UserRequest) -> PlanBundle:
        planning_request = self.condense_request(user_request.raw_request)
        request_label = "Planning digest" if planning_request != user_request.raw_request else "User request"

        if self.mode == "research":
            system_prompt = compose_system_prompt(
                (
                    "You are a research planning agent for a multi-agent investigation pipeline. "
                    "Decompose the investigation request into focused research workstreams. "
                    "Each workstream should target a specific subtopic or angle of investigation."
                ),
                self.guidance_prompt,
                section_name="research planning, topic decomposition, and investigation methodology",
            )
            user_prompt = (
                "Create a research plan bundle for the following investigation request.\n"
                "Requirements:\n"
                "- decompose the topic into focused, non-overlapping research workstreams\n"
                "- each workstream should have clear deliverables (markdown reports)\n"
                "- include a verification plan (how to cross-check findings)\n"
                "- prioritize authoritative and primary sources\n"
                "- keep workstreams small enough to be completed in one research session\n\n"
                f"{request_label}:\n{planning_request}\n\n"
                "Return JSON only."
            )
        else:
            # 기존 코드 계획 모드 (원래 prompt)
            system_prompt = compose_system_prompt(
                (
                    "You are Claude Code acting as the architecture and planning lead for a multi-agent "
                    "software delivery pipeline. Produce a compact but implementation-ready plan bundle."
                ),
                self.guidance_prompt,
                section_name="planning, specification, workflow rules, and repository expectations",
            )
            user_prompt = (
                "Create a plan bundle for the following natural language request.\n"
                "Requirements:\n"
                "- produce project brief, architecture spec, API contract, workstreams, and test plan\n"
                "- keep workstreams small and verifiable\n"
                "- make deliverables concrete enough for a coding agent to execute\n"
                "- prefer a Python-first local MVP if the request does not force another stack\n\n"
                f"{request_label}:\n{planning_request}\n\n"
                "Return JSON only."
            )

        result = self.adapter.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=PlanBundle,
        )
        assert isinstance(result, PlanBundle)
        return result
```

### 3-5. Settings에 mode 추가

**파일:** `core/settings.py`

```python
class Settings(BaseSettings):
    # ... 기존 필드들 ...
    pipeline_mode: str = "code"  # "code" 또는 "research"
```

### 3-6. CLI에서 mode 전달

**파일:** `apps/cli/main.py`

`build_orchestrator` 함수에서 settings.pipeline_mode를 각 서비스에 전달한다:

```python
def build_orchestrator(settings: Settings | None = None) -> HermesOrchestrator:
    settings = settings or get_settings()
    # ... 기존 adapter 생성 코드 ...

    planner = PlannerService(planner_adapter, guidance_prompt=guidance, 
                             mode=settings.pipeline_mode)
    executor = ExecutorService(executor_adapter, guidance_prompt=guidance,
                               mode=settings.pipeline_mode)
    reviewer = ReviewerService(reviewer_adapter, guidance_prompt=guidance,
                                mode=settings.pipeline_mode)
    tester = TestRunnerService(mode=settings.pipeline_mode)
    # ... 나머지 동일 ...
```

### 3-7. 사용법

```bash
# .env 파일에 추가
PIPELINE_MODE=research

# 실행
python -m apps.cli.main plan --request "2026년 한국 바이오테크 산업 투자 동향 분석"
python -m apps.cli.main approve <run_id> --stage plan
python -m apps.cli.main run <run_id>
```

---

## 수정 우선순위

| 순서 | 작업 | 난이도 | 영향도 |
|------|------|--------|--------|
| 1 | settings.py 하드코딩 경로 제거 | 쉬움 | 블로커 |
| 2 | Issue 4: approve 주석 추가 | 쉬움 | 가독성 |
| 3 | Issue 3: approval_stage None fallback | 쉬움 | 정확성 |
| 4 | Issue 2: stale read 수정 | 보통 | 안정성 |
| 5 | Issue 1: retry count 분리 | 보통 | 안정성 |
| 6 | Part 3 전체: 조사 파이프라인 변환 | 보통 | 기능 추가 |

---

## 주의사항

- contracts.models의 기존 Pydantic 모델(PlanBundle, ExecutionResult, ReviewReport, TestReport, TestResult 등)은 변경하지 않는다.
  조사 모드에서도 동일한 데이터 구조를 사용한다 (파일 content에 코드 대신 markdown 조사 결과가 들어갈 뿐).
- ExecutionResult의 files 필드는 GeneratedFile 리스트로, path와 content를 가진다.
  조사 모드에서는 path가 "findings/topic_1.md" 같은 형태가 되고 content가 조사 결과 markdown이 된다.
- supervisor, memory, notifier, state_machine은 수정하지 않는다. 그대로 재사용한다.
