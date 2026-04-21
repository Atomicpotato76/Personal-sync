from pathlib import Path

import pytest

from contracts.models import ExecutionResult, GeneratedFile, ResearchClaim, ResearchReport, ResearchSource, Workstream
from tests.helpers import build_orchestrator, sample_plan_bundle, FakeExecutor, FakePlanner, FakeReviewer, passing_review


def _prepare_run(tmp_path: Path) -> tuple[str, object]:
    plan = sample_plan_bundle(
        [
            Workstream(
                id="ws-memory",
                name="Memory test",
                layer="foundation",
                objective="Test memory save behavior.",
                deliverables=["reports/ws-memory.md"],
                acceptance_criteria=["saved"],
            )
        ]
    )
    orchestrator, memory = build_orchestrator(
        tmp_path,
        planner=FakePlanner(plan),
        executor=FakeExecutor({"ws-memory": [ExecutionResult(workstream_id="ws-memory", summary="ok", files=[])]}),
        reviewer=FakeReviewer({"ws-memory": [passing_review("ws-memory")]}),
    )
    run = orchestrator.create_plan("test")
    return run.run_id, memory


def test_save_execution_result_rejects_parent_traversal(tmp_path: Path) -> None:
    run_id, memory = _prepare_run(tmp_path)
    result = ExecutionResult(
        workstream_id="ws-memory",
        summary="bad",
        files=[GeneratedFile(path="../escape.txt", content="x")],
    )
    with pytest.raises(ValueError):
        memory.save_execution_result(run_id, result)


def test_save_execution_result_rejects_absolute_path(tmp_path: Path) -> None:
    run_id, memory = _prepare_run(tmp_path)
    result = ExecutionResult(
        workstream_id="ws-memory",
        summary="bad",
        files=[GeneratedFile(path="/tmp/escape.txt", content="x")],
    )
    with pytest.raises(ValueError):
        memory.save_execution_result(run_id, result)


def test_save_execution_result_accepts_workspace_relative_path_and_writes_evidence(tmp_path: Path) -> None:
    run_id, memory = _prepare_run(tmp_path)
    report = ResearchReport(
        workstream_id="ws-memory",
        scope="scope",
        claims=[
            ResearchClaim(
                claim_id="c1",
                claim="claim",
                source_ids=["s1"],
                confidence="high",
                status="supported",
            )
        ],
        sources=[ResearchSource(source_id="s1", source_type="official", tier="primary", url="https://example.com")],
    )
    result = ExecutionResult(
        workstream_id="ws-memory",
        summary="ok",
        files=[GeneratedFile(path="reports/ok.md", content="# ok")],
        research_report=report,
    )

    memory.save_execution_result(run_id, result)

    workspace = memory.get_workspace_path(run_id)
    assert (workspace / "reports/ok.md").exists()
    evidence_path = workspace / "research_evidence/ws-memory.json"
    assert evidence_path.exists()
    changed_files = memory.list_workstreams(run_id)[0]["changed_files"]
    assert "reports/ok.md" in changed_files
    assert "research_evidence/ws-memory.json" in changed_files
