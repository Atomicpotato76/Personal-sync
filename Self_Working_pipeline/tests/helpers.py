from __future__ import annotations

from pathlib import Path

from contracts.models import (
    ApiContract,
    ApprovalStage,
    ArchitectureSpec,
    ExecutionResult,
    GeneratedFile,
    PlanBundle,
    ProjectBrief,
    ReviewIssue,
    ReviewReport,
    SupervisorDecision,
    SupervisorTrace,
    TaskAssignment,
    Workstream,
)
from core.settings import Settings
from core.state_machine import HermesStateMachine
from services.memory.db import create_session_factory
from services.memory.service import MemoryService
from services.notifier.service import NullNotificationService
from services.orchestrator.service import HermesOrchestrator
from services.testing.service import TestRunnerService


def sample_plan_bundle(workstreams: list[Workstream]) -> PlanBundle:
    return PlanBundle(
        project_brief=ProjectBrief(
            title="Sample App",
            objective="Deliver a small Python app.",
            audience="Developers",
            scope=["CLI MVP"],
            deliverables=["Python module", "Tests"],
            constraints=["Use standard library only"],
        ),
        architecture_spec=ArchitectureSpec(
            overview="Simple local Python workspace.",
            components=["src module", "pytest tests"],
            data_flow=["request -> code -> tests -> package"],
            decisions=["Use local file generation"],
        ),
        api_contract=ApiContract(interfaces=["CLI"], storage=["filesystem"]),
        workstreams=workstreams,
        test_plan=["Run pytest in generated workspace"],
    )


class FakePlanner:
    def __init__(self, plan_bundle: PlanBundle) -> None:
        self.plan_bundle = plan_bundle

    def create_plan(self, user_request):
        return self.plan_bundle


class FakeExecutor:
    def __init__(self, responses: dict[str, list[ExecutionResult]]) -> None:
        self.responses = responses
        self.calls: dict[str, int] = {key: 0 for key in responses}

    def execute(self, *, assignment: TaskAssignment, plan_bundle: PlanBundle, workspace_snapshot: str, review_feedback: list[str]) -> ExecutionResult:
        attempts = self.calls.setdefault(assignment.workstream_id, 0)
        available = self.responses[assignment.workstream_id]
        index = min(attempts, len(available) - 1)
        self.calls[assignment.workstream_id] = attempts + 1
        return available[index]


class FakeReviewer:
    def __init__(self, responses: dict[str, list[ReviewReport]]) -> None:
        self.responses = responses
        self.calls: dict[str, int] = {key: 0 for key in responses}

    def review(self, *, execution_result: ExecutionResult, plan_bundle: PlanBundle) -> ReviewReport:
        attempts = self.calls.setdefault(execution_result.workstream_id, 0)
        available = self.responses[execution_result.workstream_id]
        index = min(attempts, len(available) - 1)
        self.calls[execution_result.workstream_id] = attempts + 1
        return available[index]


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def publish(self, *, event_name: str, summary) -> None:
        self.messages.append((event_name, summary.run_id))


class FakeSupervisor:
    def __init__(self, responses: dict[ApprovalStage, list[SupervisorDecision]]) -> None:
        self.responses = responses
        self.calls: dict[ApprovalStage, int] = {key: 0 for key in responses}

    class _AgentRef:
        def __init__(self, stage: ApprovalStage) -> None:
            self.agent_id = f"{stage.value}_gate_agent"

    def agent_for_stage(self, stage: ApprovalStage):
        return self._AgentRef(stage)

    def evaluate(self, *, run_id, sequence, stage, summary, direction, plan_bundle=None, stage_narrative=None, recent_events=None, test_report=None, artifact_highlights=None):
        attempts = self.calls.setdefault(stage, 0)
        available = self.responses[stage]
        index = min(attempts, len(available) - 1)
        self.calls[stage] = attempts + 1
        return available[index], SupervisorTrace(
            run_id=run_id,
            sequence=sequence,
            stage=stage,
            agent_id=f"{stage.value}_gate_agent",
            decision_source="gate_agent",
            approved=available[index].approved,
            rationale=available[index].rationale,
            risk_flags=available[index].risk_flags,
            requires_human=available[index].requires_human,
            input_digest="fake-digest",
            latency_ms=0,
            model_name="fake-model",
        )


def build_orchestrator(tmp_path: Path, *, planner, executor, reviewer, max_retries: int = 2, notifier=None) -> tuple[HermesOrchestrator, MemoryService]:
    settings = Settings(
        workspace_root=tmp_path,
        pipeline_db_path="outputs/test.db",
        anthropic_api_key="test-anthropic",
        openai_api_key="test-openai",
        max_retries_per_workstream=max_retries,
    )
    memory = MemoryService(settings=settings, session_factory=create_session_factory(settings))
    orchestrator = HermesOrchestrator(
        planner=planner,
        executor=executor,
        reviewer=reviewer,
        tester=TestRunnerService(),
        memory=memory,
        notifier=notifier or NullNotificationService(),
        state_machine=HermesStateMachine(),
        max_retries_per_workstream=max_retries,
    )
    return orchestrator, memory


def passing_review(workstream_id: str) -> ReviewReport:
    return ReviewReport(workstream_id=workstream_id, approved=True, summary="Looks good.", issues=[])


def failing_review(workstream_id: str, suggestion: str) -> ReviewReport:
    return ReviewReport(
        workstream_id=workstream_id,
        approved=False,
        summary="Needs changes.",
        issues=[ReviewIssue(severity="medium", description="Fix the implementation.", suggested_fix=suggestion)],
    )


def python_app_files(return_value: int = 3) -> list[GeneratedFile]:
    return [
        GeneratedFile(
            path="src/app.py",
            content=f"def add(a: int, b: int) -> int:\n    return {return_value}\n",
            description="Core app module",
        ),
        GeneratedFile(
            path="tests/test_app.py",
            content=(
                "import sys\n"
                "from pathlib import Path\n\n"
                "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
                "from app import add\n\n"
                "def test_add():\n"
                "    assert add(1, 2) == 3\n"
            ),
            description="Pytest coverage",
        ),
    ]


def feature_files(broken: bool) -> list[GeneratedFile]:
    feature_body = (
        "def build_message() -> str:\n"
        "    raise ValueError('feature.py needs retry')\n"
        if broken
        else "def build_message() -> str:\n    return 'ready'\n"
    )
    return [
        GeneratedFile(path="src/core.py", content="def base() -> str:\n    return 'ok'\n", description="Core module"),
        GeneratedFile(path="src/feature.py", content=feature_body, description="Feature module"),
        GeneratedFile(
            path="tests/test_feature.py",
            content=(
                "import sys\n"
                "from pathlib import Path\n\n"
                "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
                "from core import base\n"
                "from feature import build_message\n\n"
                "def test_feature():\n"
                "    assert base() == 'ok'\n"
                "    assert build_message() == 'ready'\n"
            ),
            description="Feature tests",
        ),
    ]
