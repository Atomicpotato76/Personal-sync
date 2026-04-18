import re
from pathlib import Path

from apps.gui.main import (
    approve_and_maybe_continue,
    build_status_snapshot,
    recommended_approval_stage,
    render_direction_text,
    render_overview_text,
)
from contracts.models import ApprovalStage, ExecutionResult, Workstream
from contracts.models import RunStatus, SupervisorDecision, SupervisorSession
from tests.helpers import FakeExecutor, FakePlanner, FakeReviewer, FakeSupervisor, build_orchestrator, feature_files, passing_review, python_app_files, sample_plan_bundle


def test_build_status_snapshot_includes_direction_and_stage_context(tmp_path: Path) -> None:
    plan = sample_plan_bundle(
        [
            Workstream(
                id="ws-one",
                name="Build first step",
                layer="foundation",
                objective="Create the first module.",
                deliverables=["src/core.py"],
                acceptance_criteria=["first file exists"],
            ),
            Workstream(
                id="ws-two",
                name="Build second step",
                layer="application",
                objective="Create the second module.",
                deliverables=["src/app.py", "tests/test_app.py"],
                acceptance_criteria=["pytest passes"],
            ),
        ]
    )
    executor = FakeExecutor(
        {
            "ws-one": [ExecutionResult(workstream_id="ws-one", summary="first", files=[feature_files(False)[0]])],
            "ws-two": [ExecutionResult(workstream_id="ws-two", summary="second", files=python_app_files())],
        }
    )
    reviewer = FakeReviewer({"ws-one": [passing_review("ws-one")], "ws-two": [passing_review("ws-two")]})
    orchestrator, memory = build_orchestrator(tmp_path, planner=FakePlanner(plan), executor=executor, reviewer=reviewer)

    run = orchestrator.create_plan("build in two steps")
    orchestrator.approve(run.run_id, stage=ApprovalStage.plan)
    orchestrator.run(run.run_id)

    snapshot = build_status_snapshot(memory, run.run_id)

    assert snapshot.direction is not None
    assert snapshot.direction.completed_stage == "foundation"
    assert snapshot.stage_narrative is not None
    assert snapshot.stage_narrative.stage_name == "foundation"
    assert "## 워크스트림" in snapshot.plan_summary_text
    assert "checkpoint" == recommended_approval_stage(snapshot).value
    assert "추천 승인: checkpoint" in render_overview_text(snapshot)
    direction_text = render_direction_text(snapshot)
    assert "foundation" in direction_text
    assert "방향 안내와 승인 맥락" in direction_text


def test_recommended_approval_stage_tracks_plan_and_merge_gates(tmp_path: Path) -> None:
    plan = sample_plan_bundle(
        [
            Workstream(
                id="ws-app",
                name="Build app",
                layer="backend",
                objective="Create the Python app and tests.",
                deliverables=["src/app.py", "tests/test_app.py"],
                acceptance_criteria=["pytest passes"],
            )
        ]
    )
    orchestrator, memory = build_orchestrator(
        tmp_path,
        planner=FakePlanner(plan),
        executor=FakeExecutor({"ws-app": [ExecutionResult(workstream_id="ws-app", summary="done", files=python_app_files())]}),
        reviewer=FakeReviewer({"ws-app": [passing_review("ws-app")]}),
    )

    run = orchestrator.create_plan("build a tiny app")
    planning_snapshot = build_status_snapshot(memory, run.run_id)
    assert recommended_approval_stage(planning_snapshot) == ApprovalStage.plan

    orchestrator.approve(run.run_id, stage=ApprovalStage.plan)
    orchestrator.run(run.run_id)
    testing_snapshot = build_status_snapshot(memory, run.run_id)
    assert recommended_approval_stage(testing_snapshot) == ApprovalStage.merge


def test_memory_list_runs_returns_latest_first(tmp_path: Path) -> None:
    plan = sample_plan_bundle(
        [
            Workstream(
                id="ws-app",
                name="Build app",
                layer="backend",
                objective="Create the Python app and tests.",
                deliverables=["src/app.py"],
                acceptance_criteria=["file exists"],
            )
        ]
    )
    orchestrator, memory = build_orchestrator(
        tmp_path,
        planner=FakePlanner(plan),
        executor=FakeExecutor({"ws-app": [ExecutionResult(workstream_id="ws-app", summary="done", files=python_app_files())]}),
        reviewer=FakeReviewer({"ws-app": [passing_review("ws-app")]}),
    )

    first = orchestrator.create_plan("first request")
    second = orchestrator.create_plan("second request")

    runs = memory.list_runs(limit=5)

    assert runs[0].run_id == second.run_id
    assert runs[1].run_id == first.run_id


def test_new_runs_use_date_based_plan_and_output_folders(tmp_path: Path) -> None:
    plan = sample_plan_bundle(
        [
            Workstream(
                id="ws-app",
                name="Build app",
                layer="backend",
                objective="Create the Python app and tests.",
                deliverables=["src/app.py"],
                acceptance_criteria=["file exists"],
            )
        ]
    )
    orchestrator, _memory = build_orchestrator(
        tmp_path,
        planner=FakePlanner(plan),
        executor=FakeExecutor({"ws-app": [ExecutionResult(workstream_id="ws-app", summary="done", files=python_app_files())]}),
        reviewer=FakeReviewer({"ws-app": [passing_review("ws-app")]}),
    )

    run = orchestrator.create_plan("date based folders")

    plan_path = Path(run.plan_path)
    workspace_path = Path(run.workspace_path)

    assert plan_path.name == "plan_bundle.json"
    assert workspace_path.name == "workspace"
    assert plan_path.parent.name == run.run_id
    assert workspace_path.parent.name == run.run_id
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", plan_path.parent.parent.name)
    assert plan_path.parent.parent.name == workspace_path.parent.parent.name


def test_status_snapshot_includes_supervisor_session_details(tmp_path: Path) -> None:
    plan = sample_plan_bundle(
        [
            Workstream(
                id="ws-app",
                name="Build app",
                layer="backend",
                objective="Create the Python app and tests.",
                deliverables=["src/app.py", "tests/test_app.py"],
                acceptance_criteria=["pytest passes"],
            )
        ]
    )
    orchestrator, memory = build_orchestrator(
        tmp_path,
        planner=FakePlanner(plan),
        executor=FakeExecutor({"ws-app": [ExecutionResult(workstream_id="ws-app", summary="done", files=python_app_files())]}),
        reviewer=FakeReviewer({"ws-app": [passing_review("ws-app")]}),
    )
    supervisor = FakeSupervisor({ApprovalStage.plan: []})

    run = orchestrator.create_plan("build a tiny app")
    orchestrator.supervise(run.run_id, supervisor=supervisor, max_cycles=0)

    snapshot = build_status_snapshot(memory, run.run_id)

    assert snapshot.supervisor_session is not None
    assert snapshot.supervisor_session.status == "blocked"
    assert snapshot.supervisor_traces
    assert "감독 모드:" in render_overview_text(snapshot)


def test_checkpoint_approval_auto_continues_to_next_gate(tmp_path: Path) -> None:
    plan = sample_plan_bundle(
        [
            Workstream(
                id="ws-one",
                name="Build first step",
                layer="foundation",
                objective="Create the first module.",
                deliverables=["src/core.py"],
                acceptance_criteria=["first file exists"],
            ),
            Workstream(
                id="ws-two",
                name="Build second step",
                layer="application",
                objective="Create the second module and tests.",
                deliverables=["src/app.py", "tests/test_app.py"],
                acceptance_criteria=["pytest passes"],
            ),
        ]
    )
    executor = FakeExecutor(
        {
            "ws-one": [ExecutionResult(workstream_id="ws-one", summary="first", files=[feature_files(False)[0]])],
            "ws-two": [ExecutionResult(workstream_id="ws-two", summary="second", files=python_app_files())],
        }
    )
    reviewer = FakeReviewer({"ws-one": [passing_review("ws-one")], "ws-two": [passing_review("ws-two")]})
    orchestrator, memory = build_orchestrator(tmp_path, planner=FakePlanner(plan), executor=executor, reviewer=reviewer)

    run = orchestrator.create_plan("build in two steps")
    orchestrator.approve(run.run_id, stage=ApprovalStage.plan)
    paused = orchestrator.run(run.run_id)

    assert paused.stage.value == "executing"
    assert paused.status.value == "waiting_approval"

    continued = approve_and_maybe_continue(
        orchestrator,
        run_id=run.run_id,
        stage=ApprovalStage.checkpoint,
        actor="local-user",
        comment="",
    )

    assert continued.stage.value == "testing"
    assert continued.status.value == "waiting_approval"
    snapshot = build_status_snapshot(memory, run.run_id)
    assert recommended_approval_stage(snapshot) == ApprovalStage.merge


def test_plan_approval_does_not_auto_continue(tmp_path: Path) -> None:
    plan = sample_plan_bundle(
        [
            Workstream(
                id="ws-app",
                name="Build app",
                layer="backend",
                objective="Create the Python app and tests.",
                deliverables=["src/app.py", "tests/test_app.py"],
                acceptance_criteria=["pytest passes"],
            )
        ]
    )
    orchestrator, _memory = build_orchestrator(
        tmp_path,
        planner=FakePlanner(plan),
        executor=FakeExecutor({"ws-app": [ExecutionResult(workstream_id="ws-app", summary="done", files=python_app_files())]}),
        reviewer=FakeReviewer({"ws-app": [passing_review("ws-app")]}),
    )

    run = orchestrator.create_plan("build a tiny app")
    approved = approve_and_maybe_continue(
        orchestrator,
        run_id=run.run_id,
        stage=ApprovalStage.plan,
        actor="local-user",
        comment="",
    )

    assert approved.stage.value == "plan_approved"
    assert approved.status.value == "pending"


def test_checkpoint_approval_resumes_supervisor_after_block(tmp_path: Path) -> None:
    plan = sample_plan_bundle(
        [
            Workstream(
                id="ws-one",
                name="Build first step",
                layer="foundation",
                objective="Create the first module.",
                deliverables=["src/core.py"],
                acceptance_criteria=["first file exists"],
            ),
            Workstream(
                id="ws-two",
                name="Build second step",
                layer="application",
                objective="Create the second module and tests.",
                deliverables=["src/app.py", "tests/test_app.py"],
                acceptance_criteria=["pytest passes"],
            ),
        ]
    )
    executor = FakeExecutor(
        {
            "ws-one": [ExecutionResult(workstream_id="ws-one", summary="first", files=[feature_files(False)[0]])],
            "ws-two": [ExecutionResult(workstream_id="ws-two", summary="second", files=python_app_files())],
        }
    )
    reviewer = FakeReviewer({"ws-one": [passing_review("ws-one")], "ws-two": [passing_review("ws-two")]})
    orchestrator, memory = build_orchestrator(tmp_path, planner=FakePlanner(plan), executor=executor, reviewer=reviewer)
    supervisor = FakeSupervisor(
        {
            ApprovalStage.checkpoint: [
                SupervisorDecision(stage=ApprovalStage.checkpoint, approved=True, rationale="ok")
            ],
            ApprovalStage.merge: [
                SupervisorDecision(stage=ApprovalStage.merge, approved=True, rationale="ok")
            ],
        }
    )

    run = orchestrator.create_plan("build in two steps")
    orchestrator.approve(run.run_id, stage=ApprovalStage.plan)
    paused = orchestrator.run(run.run_id)
    assert paused.stage.value == "executing"
    assert paused.status.value == "waiting_approval"

    memory.update_run(run.run_id, status=RunStatus.blocked, last_error="Supervisor requested human approval.")
    memory.save_supervisor_session(
        run.run_id,
        SupervisorSession(
            run_id=run.run_id,
            enabled=True,
            status="blocked",
            current_gate=ApprovalStage.checkpoint,
            current_agent_id="policy_guard",
            last_rationale="Supervisor requested human approval.",
            last_error_code="MAX_SAME_GATE_REPEATS",
        ),
    )

    resumed = approve_and_maybe_continue(
        orchestrator,
        run_id=run.run_id,
        stage=ApprovalStage.checkpoint,
        actor="local-user",
        comment="",
        supervisor=supervisor,
    )

    assert resumed.stage.value == "completed"
    assert resumed.status.value == "completed"
