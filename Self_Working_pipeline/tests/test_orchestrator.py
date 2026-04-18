from pathlib import Path
import zipfile

import pytest

from contracts.models import ApprovalStage, ArtifactManifest, ExecutionResult, RunStatus, SupervisorDecision, SupervisorSession, Workstream
from tests.helpers import (
    FakeExecutor,
    FakeNotifier,
    FakePlanner,
    FakeReviewer,
    FakeSupervisor,
    build_orchestrator,
    failing_review,
    feature_files,
    passing_review,
    python_app_files,
    sample_plan_bundle,
)


def test_run_requires_plan_approval(tmp_path: Path) -> None:
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
    with pytest.raises(ValueError):
        orchestrator.run(run.run_id)


def test_happy_path_packages_artifacts(tmp_path: Path) -> None:
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
    executor = FakeExecutor(
        {"ws-app": [ExecutionResult(workstream_id="ws-app", summary="done", files=python_app_files())]}
    )
    reviewer = FakeReviewer({"ws-app": [passing_review("ws-app")]})
    orchestrator, memory = build_orchestrator(tmp_path, planner=FakePlanner(plan), executor=executor, reviewer=reviewer)

    run = orchestrator.create_plan("build a tiny app")
    run = orchestrator.approve(run.run_id, stage=ApprovalStage.plan)
    run = orchestrator.run(run.run_id)
    assert run.stage.value == "testing"
    assert run.status.value == "waiting_approval"

    run = orchestrator.approve(run.run_id, stage=ApprovalStage.merge)
    run = orchestrator.run(run.run_id)
    assert run.stage.value == "completed"
    assert run.manifest_path is not None

    manifest_path = Path(run.manifest_path)
    assert manifest_path.exists()
    manifest = ArtifactManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    package_path = Path(manifest.package_path)
    assert package_path.exists()
    with zipfile.ZipFile(package_path) as bundle:
        assert "src/app.py" in bundle.namelist()
        assert "tests/test_app.py" in bundle.namelist()


def test_review_failure_retries_single_workstream(tmp_path: Path) -> None:
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
    executor = FakeExecutor(
        {
            "ws-app": [
                ExecutionResult(workstream_id="ws-app", summary="first draft", files=python_app_files(return_value=0)),
                ExecutionResult(workstream_id="ws-app", summary="fixed", files=python_app_files(return_value=3)),
            ]
        }
    )
    reviewer = FakeReviewer(
        {
            "ws-app": [
                failing_review("ws-app", "Make add(1, 2) return 3."),
                passing_review("ws-app"),
            ]
        }
    )
    orchestrator, memory = build_orchestrator(tmp_path, planner=FakePlanner(plan), executor=executor, reviewer=reviewer)

    run = orchestrator.create_plan("build a tiny app")
    orchestrator.approve(run.run_id, stage=ApprovalStage.plan)
    run = orchestrator.run(run.run_id)
    assert run.stage.value == "testing"
    assert run.status.value == "waiting_approval"
    workstream = memory.list_workstreams(run.run_id)[0]
    assert workstream["status"] == "completed"
    assert workstream["retry_count"] == 1
    assert executor.calls["ws-app"] == 2


def test_test_failure_retries_only_impacted_workstream(tmp_path: Path) -> None:
    plan = sample_plan_bundle(
        [
            Workstream(
                id="ws-core",
                name="Build core",
                layer="foundation",
                objective="Create shared core utilities.",
                deliverables=["src/core.py"],
                acceptance_criteria=["Core utilities exist"],
            ),
            Workstream(
                id="ws-feature",
                name="Build feature",
                layer="feature",
                objective="Create feature logic and tests.",
                deliverables=["src/feature.py", "tests/test_feature.py"],
                acceptance_criteria=["pytest passes"],
                dependencies=["ws-core"],
            ),
        ]
    )
    executor = FakeExecutor(
        {
            "ws-core": [ExecutionResult(workstream_id="ws-core", summary="core done", files=[feature_files(False)[0]])],
            "ws-feature": [
                ExecutionResult(workstream_id="ws-feature", summary="broken feature", files=feature_files(True)[1:]),
                ExecutionResult(workstream_id="ws-feature", summary="fixed feature", files=feature_files(False)[1:]),
            ],
        }
    )
    reviewer = FakeReviewer(
        {
            "ws-core": [passing_review("ws-core")],
            "ws-feature": [passing_review("ws-feature"), passing_review("ws-feature")],
        }
    )
    orchestrator, memory = build_orchestrator(tmp_path, planner=FakePlanner(plan), executor=executor, reviewer=reviewer)

    run = orchestrator.create_plan("build a feature app")
    orchestrator.approve(run.run_id, stage=ApprovalStage.plan)
    run = orchestrator.run(run.run_id)
    assert run.stage.value == "executing"
    assert run.status.value == "waiting_approval"
    run = orchestrator.approve(run.run_id, stage=ApprovalStage.checkpoint)
    run = orchestrator.run(run.run_id)
    assert run.stage.value == "executing"
    assert run.status.value == "waiting_approval"
    run = orchestrator.approve(run.run_id, stage=ApprovalStage.checkpoint)
    run = orchestrator.run(run.run_id)

    assert run.stage.value == "testing"
    assert run.status.value == "waiting_approval"
    assert executor.calls["ws-core"] == 1
    assert executor.calls["ws-feature"] == 2

    workstreams = {item["workstream_id"]: item for item in memory.list_workstreams(run.run_id)}
    assert workstreams["ws-core"]["retry_count"] == 0
    assert workstreams["ws-feature"]["retry_count"] == 1


def test_checkpoint_approval_pauses_between_workstreams(tmp_path: Path) -> None:
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
    run = orchestrator.run(run.run_id)

    assert run.stage.value == "executing"
    assert run.status.value == "waiting_approval"
    summary = memory.build_checkpoint_summary(run.run_id)
    latest_direction = memory.get_latest_direction(run.run_id)
    latest_stage_narrative = memory.get_latest_stage_narrative(run.run_id)
    assert summary.completed == ["Build first step"]
    assert "체크포인트" in summary.overview
    assert summary.latest_stage_name == "foundation"
    assert summary.latest_stage_summary is not None
    assert latest_direction is not None
    assert latest_direction.trigger_event == "stage_completed"
    assert latest_direction.completed_stage == "foundation"
    assert latest_direction.client_summary is not None
    assert latest_stage_narrative is not None
    assert latest_stage_narrative.stage_name == "foundation"

    narrative_path = Path(run.plan_path).parent / "stage_narratives" / "latest_stage.md"
    assert narrative_path.exists()
    assert "## 쉬운 설명" in narrative_path.read_text(encoding="utf-8")

    orchestrator.approve(run.run_id, stage=ApprovalStage.checkpoint)
    run = orchestrator.run(run.run_id)
    assert run.stage.value == "testing"
    assert run.status.value == "waiting_approval"
    latest_direction = memory.get_latest_direction(run.run_id)
    assert latest_direction is not None
    assert latest_direction.trigger_event == "tests_passed_waiting_merge"


def test_checkpoint_approval_can_resume_after_supervisor_block(tmp_path: Path) -> None:
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
    run = orchestrator.run(run.run_id)
    assert run.stage.value == "executing"
    assert run.status.value == "waiting_approval"

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

    approved = orchestrator.approve(run.run_id, stage=ApprovalStage.checkpoint)
    assert approved.status == RunStatus.pending
    resumed = orchestrator.run(run.run_id)

    assert resumed.stage.value == "testing"
    assert resumed.status.value == "waiting_approval"
    latest_session = memory.get_latest_supervisor_session(run.run_id)
    assert latest_session is not None
    assert latest_session.status == "manual_override"
    assert latest_session.current_gate is None
    events = [event.event_type for event in memory.list_events(run.run_id, limit=20)]
    assert "supervisor_manual_override" in events


def test_feedback_creates_new_plan_version(tmp_path: Path) -> None:
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
    orchestrator.record_feedback(run.run_id, "Add a simple CSV export option for future users.")

    latest_plan = memory.load_plan_bundle(run.run_id)
    assert len(latest_plan.change_log) == 1
    assert latest_plan.change_log[0].additions == ["Add a simple CSV export option for future users."]
    assert memory.get_plan_version(run.run_id) == 2
    summary_text = Path(run.plan_path).parent.joinpath("summary.md").read_text(encoding="utf-8")
    assert "추가된 방향" in summary_text
    assert "Add a simple CSV export option for future users." in summary_text


def test_notifier_receives_checkpoint_and_manual_status(tmp_path: Path) -> None:
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
    notifier = FakeNotifier()
    orchestrator, _memory = build_orchestrator(
        tmp_path,
        planner=FakePlanner(plan),
        executor=FakeExecutor(
            {
                "ws-one": [ExecutionResult(workstream_id="ws-one", summary="first", files=[feature_files(False)[0]])],
                "ws-two": [ExecutionResult(workstream_id="ws-two", summary="second", files=python_app_files())],
            }
        ),
        reviewer=FakeReviewer({"ws-one": [passing_review("ws-one")], "ws-two": [passing_review("ws-two")]}),
        notifier=notifier,
    )

    run = orchestrator.create_plan("build in two steps")
    assert notifier.messages[0] == ("plan_ready", run.run_id)
    orchestrator.approve(run.run_id, stage=ApprovalStage.plan)
    run = orchestrator.run(run.run_id)
    assert ("stage_completed", run.run_id) in notifier.messages
    orchestrator.notify_status(run.run_id)
    assert notifier.messages[-1] == ("manual_status", run.run_id)


def test_single_stage_runs_all_workstreams_before_pausing(tmp_path: Path) -> None:
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
                layer="foundation",
                objective="Create the second module and tests.",
                deliverables=["src/app.py", "tests/test_app.py"],
                acceptance_criteria=["pytest passes"],
            ),
            Workstream(
                id="ws-three",
                name="Build third step",
                layer="application",
                objective="Create the third module.",
                deliverables=["src/feature.py"],
                acceptance_criteria=["feature exists"],
            ),
        ]
    )
    executor = FakeExecutor(
        {
            "ws-one": [ExecutionResult(workstream_id="ws-one", summary="first", files=[feature_files(False)[0]])],
            "ws-two": [ExecutionResult(workstream_id="ws-two", summary="second", files=python_app_files())],
            "ws-three": [ExecutionResult(workstream_id="ws-three", summary="third", files=[feature_files(False)[1]])],
        }
    )
    reviewer = FakeReviewer(
        {
            "ws-one": [passing_review("ws-one")],
            "ws-two": [passing_review("ws-two")],
            "ws-three": [passing_review("ws-three")],
        }
    )
    orchestrator, memory = build_orchestrator(tmp_path, planner=FakePlanner(plan), executor=executor, reviewer=reviewer)

    run = orchestrator.create_plan("build in stage groups")
    orchestrator.approve(run.run_id, stage=ApprovalStage.plan)
    run = orchestrator.run(run.run_id)

    assert run.stage.value == "executing"
    assert run.status.value == "waiting_approval"
    assert executor.calls["ws-one"] == 1
    assert executor.calls["ws-two"] == 1
    assert executor.calls["ws-three"] == 0

    workstreams = {item["workstream_id"]: item for item in memory.list_workstreams(run.run_id)}
    assert workstreams["ws-one"]["status"] == "completed"
    assert workstreams["ws-two"]["status"] == "completed"
    assert workstreams["ws-three"]["status"] == "pending"


def test_final_stage_emits_stage_completed_notification(tmp_path: Path) -> None:
    # Single-stage plan: when everything finishes, the pipeline falls through to testing.
    # It should still emit a per-chunk confirmation for that final stage before moving on.
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
    notifier = FakeNotifier()
    orchestrator, memory = build_orchestrator(
        tmp_path,
        planner=FakePlanner(plan),
        executor=FakeExecutor(
            {"ws-app": [ExecutionResult(workstream_id="ws-app", summary="done", files=python_app_files())]}
        ),
        reviewer=FakeReviewer({"ws-app": [passing_review("ws-app")]}),
        notifier=notifier,
    )

    run = orchestrator.create_plan("build a tiny app")
    orchestrator.approve(run.run_id, stage=ApprovalStage.plan)
    run = orchestrator.run(run.run_id)

    # The run proceeds to testing (single stage = no checkpoint pause),
    # but we still need a confirmation that the final stage/chunk is done.
    assert run.stage.value == "testing"
    event_names = [name for name, _run_id in notifier.messages]
    assert "stage_completed" in event_names, (
        f"expected stage_completed before testing, got: {event_names}"
    )
    # And the narrative itself must have been saved so downstream UI can render it.
    narrative = memory.get_latest_stage_narrative(run.run_id)
    assert narrative is not None
    assert narrative.stage_name == "backend"


def test_discord_notifier_includes_stage_narrative_highlight() -> None:
    from contracts.models import CheckpointSummary, RunStage, RunStatus
    from services.notifier.service import DiscordWebhookNotificationService

    service = DiscordWebhookNotificationService(webhook_url="http://unused.invalid/")
    summary = CheckpointSummary(
        run_id="abc123",
        stage=RunStage.executing,
        status=RunStatus.waiting_approval,
        plan_version=1,
        overview="foundation 단계 이후 체크포인트에서 검토 대기 중입니다.",
        completed=["Build first step"],
        in_progress=[],
        pending=["Build second step"],
        next_step="승인 후 계속 진행하세요.",
        latest_stage_name="foundation",
        latest_stage_summary="foundation 단계가 끝났고 src/core.py가 생성되었습니다.",
    )

    rendered = service._render_message(event_name="stage_completed", summary=summary)

    assert "방금 완료된 단계" in rendered
    assert "foundation" in rendered
    assert "src/core.py" in rendered


def test_supervisor_can_auto_approve_run_to_completion(tmp_path: Path) -> None:
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
    orchestrator, memory = build_orchestrator(
        tmp_path,
        planner=FakePlanner(plan),
        executor=FakeExecutor(
            {
                "ws-one": [ExecutionResult(workstream_id="ws-one", summary="first", files=[feature_files(False)[0]])],
                "ws-two": [ExecutionResult(workstream_id="ws-two", summary="second", files=python_app_files())],
            }
        ),
        reviewer=FakeReviewer({"ws-one": [passing_review("ws-one")], "ws-two": [passing_review("ws-two")]}),
    )
    supervisor = FakeSupervisor(
        {
            ApprovalStage.plan: [SupervisorDecision(stage=ApprovalStage.plan, approved=True, rationale="Plan is coherent.")],
            ApprovalStage.checkpoint: [
                SupervisorDecision(stage=ApprovalStage.checkpoint, approved=True, rationale="Checkpoint direction is clear.")
            ],
            ApprovalStage.merge: [SupervisorDecision(stage=ApprovalStage.merge, approved=True, rationale="Tests passed cleanly.")],
        }
    )

    run = orchestrator.create_plan("build in two steps")
    run = orchestrator.supervise(run.run_id, supervisor=supervisor)

    assert run.stage.value == "completed"
    assert run.status.value == "completed"
    assert run.manifest_path is not None
    assert memory.get_latest_direction(run.run_id) is not None
    assert memory.get_latest_supervisor_session(run.run_id) is not None
    assert memory.get_latest_supervisor_trace(run.run_id) is not None
    events = [event.event_type for event in memory.list_events(run.run_id, limit=50)]
    assert "supervisor_agent_decision" in events
    assert "supervisor_session_completed" in events


def test_supervisor_blocks_run_when_direction_is_not_ready(tmp_path: Path) -> None:
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
    supervisor = FakeSupervisor(
        {
            ApprovalStage.plan: [
                SupervisorDecision(
                    stage=ApprovalStage.plan,
                    approved=False,
                    rationale="User should confirm the direction before coding starts.",
                )
            ]
        }
    )

    run = orchestrator.create_plan("build a tiny app")
    run = orchestrator.supervise(run.run_id, supervisor=supervisor)

    assert run.stage.value == "planning"
    assert run.status.value == "blocked"
    assert run.last_error == "User should confirm the direction before coding starts."
    summary = memory.build_checkpoint_summary(run.run_id)
    assert "자동 승인하지 않고" in summary.overview
    trace = memory.get_latest_supervisor_trace(run.run_id)
    assert trace is not None
    assert trace.agent_id == "plan_gate_agent"


def test_supervisor_policy_guard_blocks_when_cycle_limit_is_zero(tmp_path: Path) -> None:
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
    supervisor = FakeSupervisor({ApprovalStage.plan: [SupervisorDecision(stage=ApprovalStage.plan, approved=True, rationale="unused")]})

    run = orchestrator.create_plan("build a tiny app")
    run = orchestrator.supervise(run.run_id, supervisor=supervisor, max_cycles=0)

    assert run.status.value == "blocked"
    trace = memory.get_latest_supervisor_trace(run.run_id)
    assert trace is not None
    assert trace.agent_id == "policy_guard"
    assert trace.error_code == "MAX_CYCLES"


def test_supervisor_blocks_when_same_gate_repeat_limit_is_reached(tmp_path: Path) -> None:
    plan = sample_plan_bundle(
        [
            Workstream(
                id=f"ws-{index}",
                name=f"Build step {index}",
                layer=f"layer-{index}",
                objective=f"Create module {index}.",
                deliverables=[f"src/module_{index}.py"],
                acceptance_criteria=["file exists"],
            )
            for index in range(1, 6)
        ]
    )
    executor = FakeExecutor(
        {
            f"ws-{index}": [
                ExecutionResult(
                    workstream_id=f"ws-{index}",
                    summary=f"step {index}",
                    files=[feature_files(False)[0]],
                )
            ]
            for index in range(1, 6)
        }
    )
    reviewer = FakeReviewer({f"ws-{index}": [passing_review(f"ws-{index}")] for index in range(1, 6)})
    orchestrator, memory = build_orchestrator(tmp_path, planner=FakePlanner(plan), executor=executor, reviewer=reviewer)
    supervisor = FakeSupervisor(
        {
            ApprovalStage.plan: [SupervisorDecision(stage=ApprovalStage.plan, approved=True, rationale="ok")],
            ApprovalStage.checkpoint: [
                SupervisorDecision(stage=ApprovalStage.checkpoint, approved=True, rationale="ok")
                for _ in range(4)
            ],
            ApprovalStage.merge: [SupervisorDecision(stage=ApprovalStage.merge, approved=True, rationale="ok")],
        }
    )

    run = orchestrator.create_plan("many checkpoint gates")
    run = orchestrator.supervise(run.run_id, supervisor=supervisor, max_cycles=10)

    assert run.status.value == "blocked"
    trace = memory.get_latest_supervisor_trace(run.run_id)
    assert trace is not None
    assert trace.error_code == "MAX_SAME_GATE_REPEATS"


def test_supervisor_blocks_when_plan_revision_limit_is_reached(tmp_path: Path) -> None:
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
    memory.settings.supervisor_max_plan_revisions = 2
    supervisor = FakeSupervisor(
        {
            ApprovalStage.plan: [SupervisorDecision(stage=ApprovalStage.plan, approved=True, rationale="unused")],
        }
    )

    run = orchestrator.create_plan("build a tiny app")
    memory.append_plan_addition(run.run_id, "Narrow the scope to a first MVP.")
    memory.append_plan_addition(run.run_id, "Add a second planning clarification.")

    run = orchestrator.supervise(run.run_id, supervisor=supervisor)

    assert run.stage.value == "planning"
    assert run.status.value == "blocked"
    assert supervisor.calls[ApprovalStage.plan] == 0
    trace = memory.get_latest_supervisor_trace(run.run_id)
    assert trace is not None
    assert trace.agent_id == "policy_guard"
    assert trace.error_code == "MAX_PLAN_REVISIONS"
